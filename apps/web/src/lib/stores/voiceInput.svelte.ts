import { sttApi, type TranscribeResult } from '$lib/api/stt';
import { startMicCapture, type MicCapture } from '$lib/audio/micCapture';
import { encodeWav16k, resampleLinear } from '$lib/audio/wavEncode';
import { createVad } from '$lib/audio/vad';

export const PTT_MAX_MS = 120_000;          // spec §4: PTT 録音上限
export const HANDSFREE_MAX_FAILURES = 3;    // spec §7: 連続失敗で自動オフ

export type VoiceStatus = 'idle' | 'capturing' | 'recording' | 'transcribing' | 'handsfree';

export interface VoiceInputCallbacks {
  onText(text: string): void;
  onError(message: string): void;
}

interface Deps {
  capture?: (onChunk: (samples: Float32Array, sampleRate: number) => void) => Promise<MicCapture>;
  api?: { transcribe(blob: Blob): Promise<TranscribeResult> };
}

export function createVoiceInputStore(deps: Deps = {}) {
  const capture = deps.capture ?? startMicCapture;
  const api = deps.api ?? sttApi;

  let status = $state<VoiceStatus>('idle');
  let elapsedSec = $state(0);

  let cb: VoiceInputCallbacks = { onText: () => {}, onError: () => {} };
  let mic: MicCapture | null = null;
  let chunks: Float32Array[] = [];
  let sampleRate = 16000;
  let elapsedTimer: ReturnType<typeof setInterval> | null = null;
  let maxTimer: ReturnType<typeof setTimeout> | null = null;

  // ハンズフリー: 挿入順序を守るための直列キューと連続失敗カウンタ
  let queue: Promise<void> = Promise.resolve();
  let failures = 0;
  let vad: ReturnType<typeof createVad> | null = null;
  // ハンズフリー: セッション単位のキャンセルトークンと世代番号。
  // 手動オフは発話中の最終区間を変換してから終わる(Claude Code の tap-to-stop と同型)ため
  // トークンを立てない。強制オフ(3 連続失敗・stopAll)はトークンを立てて破棄する。
  let hfCancel: { value: boolean } | null = null;
  let hfGen = 0;

  function collect(samples: Float32Array, sr: number) {
    sampleRate = sr;
    chunks.push(samples);
  }

  function concatChunks(): Float32Array {
    const total = chunks.reduce((n, c) => n + c.length, 0);
    const out = new Float32Array(total);
    let o = 0;
    for (const c of chunks) {
      out.set(c, o);
      o += c.length;
    }
    return out;
  }

  function stopMic() {
    mic?.stop();
    mic = null;
  }

  function clearTimers() {
    if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null; }
    if (maxTimer) { clearTimeout(maxTimer); maxTimer = null; }
    elapsedSec = 0;
  }

  async function transcribeAndEmit(samples: Float32Array, sr: number): Promise<void> {
    const result = await api.transcribe(encodeWav16k(samples, sr));
    if (result.text) {
      cb.onText(result.text);
    } else {
      cb.onError('音声を認識できませんでした');
    }
  }

  const store = {
    get status() { return status; },
    get elapsedSec() { return elapsedSec; },

    setCallbacks(next: VoiceInputCallbacks) { cb = next; },

    /** PTT keydown: タップかもしれないのでキャプチャだけ先行開始(語頭欠落防止)。 */
    pttPressStart() {
      if (status !== 'idle') return;
      status = 'capturing';
      chunks = [];
      void capture(collect).then(
        (m) => {
          // 起動中に tap で破棄済みなら即停止
          if (status !== 'capturing' && status !== 'recording') { m.stop(); return; }
          mic = m;
        },
        (e) => {
          status = 'idle';
          cb.onError(e instanceof Error && e.name === 'NotAllowedError'
            ? 'マイクへのアクセスが拒否されました'
            : `マイクを開始できませんでした: ${e instanceof Error ? e.message : String(e)}`);
        },
      );
    },

    /** タップ確定: バッファ破棄(文字挿入は呼び出し側 ChatInput が行う)。 */
    pttTapCancel() {
      stopMic();
      clearTimers(); // 'recording' 中の誤順序呼び出しでもタイマーをリークさせない
      chunks = [];
      status = 'idle';
    },

    /** 長押し確定: 録音中 UI へ。120 秒で自動確定。 */
    pttHoldStart() {
      if (status !== 'capturing') return;
      status = 'recording';
      const started = Date.now();
      elapsedTimer = setInterval(() => { elapsedSec = Math.floor((Date.now() - started) / 1000); }, 250);
      maxTimer = setTimeout(() => { void store.pttHoldEnd(); }, PTT_MAX_MS);
    },

    /** 解放: 停止 → WAV → 認識 → onText。 */
    async pttHoldEnd() {
      if (status !== 'recording') return;
      stopMic();
      clearTimers();
      const samples = concatChunks();
      chunks = [];
      status = 'transcribing';
      try {
        await transcribeAndEmit(samples, sampleRate);
      } catch (e) {
        cb.onError(e instanceof Error ? e.message : String(e));
      } finally {
        status = 'idle';
      }
    },

    /** ハンズフリーのオン/オフ。オン中は VAD が発話区間ごとに直列 POST。 */
    async handsFreeToggle() {
      if (status === 'handsfree') {
        // 手動オフ: 先に flush して発話中の最終区間をキューに確定させる。
        // キャンセルトークンは立てないため、この区間は変換され onText に届く。
        vad?.flush();
        vad = null;
        stopMic();
        status = 'idle';
        return;
      }
      if (status !== 'idle') return;
      failures = 0;
      status = 'handsfree';
      const cancelled = { value: false };
      hfCancel = cancelled;
      const myGen = ++hfGen;
      const localVad = createVad({
        sampleRate: 16000,
        onSegment: (samples) => {
          const sr = sampleRate;
          queue = queue.then(async () => {
            if (cancelled.value) return;
            try {
              await transcribeAndEmitHandsFree(samples, sr);
            } catch (e) {
              failures += 1;
              if (failures >= HANDSFREE_MAX_FAILURES) {
                cancelled.value = true; // 強制オフ: 残キュー区間は破棄
                cb.onError(
                  `変換に${HANDSFREE_MAX_FAILURES}回連続で失敗したためハンズフリーを停止しました: ` +
                  (e instanceof Error ? e.message : String(e)),
                );
                vad = null;
                stopMic();
                status = 'idle';
              }
            }
          });
        },
      });
      vad = localVad;
      try {
        // VAD は 16k 前提の時間パラメータで生成しているため、キャプチャ実レート
        // (44.1k/48k)のチャンクは push 前に 16k へリサンプルして統一する。
        const m = await capture((samples, sr) => {
          sampleRate = 16000;
          localVad.push(sr === 16000 ? samples : resampleLinear(samples, sr, 16000));
        });
        // 許可プロンプト待ちの間にオフへトグル済み、または別セッションが
        // 開始済み(オフ→オン→オンの二重採用)なら、遅延解決したキャプチャを
        // 即停止して破棄する(マイクストリームのリーク防止)
        if (myGen !== hfGen || status !== 'handsfree') {
          m.stop();
          return;
        }
        mic = m;
      } catch (e) {
        vad = null;
        status = 'idle';
        cb.onError(e instanceof Error && e.name === 'NotAllowedError'
          ? 'マイクへのアクセスが拒否されました'
          : `マイクを開始できませんでした: ${e instanceof Error ? e.message : String(e)}`);
      }
    },

    /** モード切替・unmount 時の後始末。キュー済みのハンズフリー区間も破棄する。 */
    stopAll() {
      if (hfCancel) hfCancel.value = true;
      stopMic();
      clearTimers();
      vad = null;
      chunks = [];
      status = 'idle';
    },
  };

  async function transcribeAndEmitHandsFree(samples: Float32Array, sr: number) {
    const result = await api.transcribe(encodeWav16k(samples, sr));
    failures = 0;
    // ハンズフリーの空認識は常態なので無通知でスキップ(spec §7)
    if (result.text) cb.onText(result.text);
  }

  return store;
}

export const voiceInputStore = createVoiceInputStore();

import { recordingsApi } from '$lib/api/recordings';
import { currentNotebookStore } from './currentNotebook.svelte';
import type { CurrentNotebookStore } from './currentNotebook.svelte';
import type { Source } from '$lib/api/types';

export interface LiveCaption {
  id: string;
  label: string;
  text: string;
  start_ms: number;
  is_final: boolean;
}

export interface RecordingStore {
  readonly recording: boolean;
  /** start() の API 応答待ち。クリック直後の optimistic pending 表示に使う。 */
  readonly starting: boolean;
  /** stop() の API 応答待ち。 */
  readonly stopping: boolean;
  readonly recordingId: string | null;
  readonly sourceId: string | null;
  readonly notebookId: string | null;
  liveCaptionEnabled: boolean;
  readonly liveCaptionActive: boolean;
  readonly elapsedMs: number;
  readonly captions: LiveCaption[];
  readonly micLevel: number;
  readonly sysLevel: number;
  readonly micMuted: boolean;
  readonly systemMuted: boolean;
  readonly error: string | null;
  start(notebookId: string, opts?: { presentationSourceId?: string }): Promise<void>;
  stop(): Promise<void>;
  toggleLiveCaption(): void;
  toggleMute(channel: MuteChannel): void;
}

export type MuteChannel = 'mic' | 'system';

const MAX_CAPTIONS = 200;

/** dB (-80..0) を 0..1 のメータ比率へ。-80dB=0、0dB=1。 */
function dbToLevel(db: number): number {
  const clamped = Math.max(-80, Math.min(0, db));
  return (clamped + 80) / 80;
}

export function createRecordingStore(
  api = recordingsApi,
  nbStore: CurrentNotebookStore = currentNotebookStore,
): RecordingStore {
  let recording = $state(false);
  let starting = $state(false);
  let stopping = $state(false);
  let recordingId = $state<string | null>(null);
  let sourceId = $state<string | null>(null);
  let notebookId = $state<string | null>(null);
  let liveCaptionEnabled = $state(true);
  let liveCaptionActive = $state(false);
  let elapsedMs = $state(0);
  let captions = $state<LiveCaption[]>([]);
  let micLevel = $state(0);
  let sysLevel = $state(0);
  let micMuted = $state(false);
  let systemMuted = $state(false);
  let error = $state<string | null>(null);

  let timer: ReturnType<typeof setInterval> | null = null;
  let startedAt = 0;
  let ws: WebSocket | null = null;
  // 意図的なクローズ(stop)か、ネットワーク/サーバ起因の切断かを区別する。
  // 後者だけ自動再接続する(前者で再接続するとゾンビ接続になる)。
  let intentionalClose = false;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let reconnectAttempts = 0;

  function clearTimer() {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  }

  function clearReconnect() {
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  }

  function closeWs() {
    intentionalClose = true; // これ以降の onclose で再接続しない
    clearReconnect();
    if (ws) {
      // onclose は破棄処理を呼ばないよう外しておく
      ws.onopen = null;
      ws.onmessage = null;
      ws.onerror = null;
      ws.onclose = null;
      try {
        ws.close();
      } catch {
        // ignore
      }
      ws = null;
    }
  }

  function resetTransient() {
    clearTimer();
    closeWs();
    recording = false;
    recordingId = null;
    sourceId = null;
    notebookId = null;
    liveCaptionActive = false;
    elapsedMs = 0;
    captions = [];
    micLevel = 0;
    sysLevel = 0;
    micMuted = false;
    systemMuted = false;
    startedAt = 0;
    reconnectAttempts = 0;
  }

  function handleMessage(raw: string) {
    let msg: Record<string, unknown>;
    try {
      msg = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return;
    }
    const type = msg.type;
    if (type === 'caption') {
      const cap: LiveCaption = {
        id: String(msg.id ?? ''),
        label: String(msg.label ?? ''),
        text: String(msg.text ?? ''),
        start_ms: Number(msg.start_ms ?? 0),
        is_final: Boolean(msg.is_final),
      };
      // ミュート中チャンネルの新規字幕は追加しない(過去分は残す)。
      // サーバ側でも送出は止まるが、操作直後の往復遅延で在庫フレームが
      // 届く場合に備えた防御的ガード。ラベル「あなた」=mic / それ以外=system。
      const capMuted = cap.label === 'あなた' ? micMuted : systemMuted;
      if (capMuted) {
        return;
      }
      const idx = captions.findIndex((c) => c.id === cap.id);
      if (idx >= 0) {
        captions = captions.map((c, i) => (i === idx ? cap : c));
      } else {
        const next = [...captions, cap];
        captions = next.length > MAX_CAPTIONS ? next.slice(-MAX_CAPTIONS) : next;
      }
    } else if (type === 'level') {
      const channel = String(msg.channel ?? '');
      const db = Number(msg.rms_db ?? -80);
      const level = dbToLevel(db);
      if (channel === 'mic') {
        micLevel = level;
      } else if (channel === 'system') {
        sysLevel = level;
      }
    } else if (type === 'mute_state') {
      // サーバからのミュート状態同期(確定値)。楽観更新と一致させる。
      const channel = String(msg.channel ?? '');
      const muted = Boolean(msg.muted);
      if (channel === 'mic') {
        micMuted = muted;
      } else if (channel === 'system') {
        systemMuted = muted;
      }
    } else if (type === 'error') {
      error = String(msg.msg ?? 'recording error');
    }
  }

  /** ミュートコマンドを送信し、送信できたか(WS が OPEN だったか)を返す。 */
  function sendMute(channel: MuteChannel, muted: boolean): boolean {
    if (ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type: 'mute', channel, muted }));
        return true;
      } catch {
        return false;
      }
    }
    return false;
  }

  /** 接続確立/再接続時に、UI が保持する現在のミュート状態をサーバへ再送して同期する。 */
  function resyncMute(socket: WebSocket) {
    if (socket.readyState !== WebSocket.OPEN) return;
    const states: Array<[MuteChannel, boolean]> = [
      ['mic', micMuted],
      ['system', systemMuted],
    ];
    for (const [channel, muted] of states) {
      try {
        socket.send(JSON.stringify({ type: 'mute', channel, muted }));
      } catch {
        // ignore — onclose 経由で再接続が走る
      }
    }
  }

  function scheduleReconnect(rid: string) {
    if (intentionalClose || !recording) return;
    // 指数バックオフ(最大 8s)。録音継続中のみ再接続する。
    const delay = Math.min(8000, 500 * 2 ** reconnectAttempts);
    reconnectAttempts += 1;
    clearReconnect();
    reconnectTimer = setTimeout(() => {
      if (!intentionalClose && recording) connectWs(rid);
    }, delay);
  }

  function connectWs(rid: string) {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const socket = new WebSocket(
      `${proto}://${location.host}/ws/recordings/${rid}/live`,
    );
    socket.onopen = () => {
      reconnectAttempts = 0;
      // 再接続でつながったら接続エラー表示をクリアし、現ミュート状態を再送して同期。
      if (error === 'ライブ字幕の接続でエラーが発生しました') error = null;
      resyncMute(socket);
    };
    socket.onmessage = (e) => handleMessage(e.data as string);
    socket.onerror = () => {
      error = 'ライブ字幕の接続でエラーが発生しました';
    };
    socket.onclose = () => {
      // 意図的な停止でなく録音継続中なら自動再接続(切断中の乖離固定化を防ぐ)。
      if (!intentionalClose && recording) scheduleReconnect(rid);
    };
    ws = socket;
  }

  return {
    get recording() {
      return recording;
    },
    get starting() {
      return starting;
    },
    get stopping() {
      return stopping;
    },
    get recordingId() {
      return recordingId;
    },
    get sourceId() {
      return sourceId;
    },
    get notebookId() {
      return notebookId;
    },
    get liveCaptionEnabled() {
      return liveCaptionEnabled;
    },
    set liveCaptionEnabled(v: boolean) {
      liveCaptionEnabled = v;
    },
    get liveCaptionActive() {
      return liveCaptionActive;
    },
    get elapsedMs() {
      return elapsedMs;
    },
    get captions() {
      return captions;
    },
    get micLevel() {
      return micLevel;
    },
    get sysLevel() {
      return sysLevel;
    },
    get micMuted() {
      return micMuted;
    },
    get systemMuted() {
      return systemMuted;
    },
    get error() {
      return error;
    },
    async start(nbId, opts = {}) {
      if (recording || starting) return;
      error = null;
      // optimistic pending: API 応答を待たずにボタンを即座に反応させる。
      // 失敗時は finally で戻り、recording は false のままなのでロールバック不要。
      starting = true;
      try {
        // 発表モード(presentation.svelte.ts から透過): opts.presentationSourceId が
        // undefined なら JSON.stringify がキーごと落とすため、backend の通常録音
        // パス(presentation_source_id 省略 = null 扱い)に落ちる。
        const started = await api.start(nbId, {
          live_caption: liveCaptionEnabled,
          presentation_source_id: opts.presentationSourceId,
        });
        recording = true;
        recordingId = started.recording_id;
        sourceId = started.source_id;
        notebookId = nbId;
        liveCaptionActive = started.live_caption;
        captions = [];
        micLevel = 0;
        sysLevel = 0;
        elapsedMs = 0;
        startedAt = Date.now();
        micMuted = false;
        systemMuted = false;
        clearTimer();
        timer = setInterval(() => {
          elapsedMs = Date.now() - startedAt;
        }, 200);
        intentionalClose = false; // 新規接続。onclose での自動再接続を許可する
        reconnectAttempts = 0;
        connectWs(started.recording_id);
      } finally {
        starting = false;
      }
    },
    async stop() {
      if (stopping) return;
      stopping = true;
      const nbId = notebookId;
      const rid = recordingId;
      const sid = sourceId; // resetTransient() が null 化する前に捕捉
      // タイマーと WS は即座に止める (UI を録音中表示のまま固めない)
      clearTimer();
      closeWs();
      try {
        if (nbId && rid) {
          await api.stop(nbId, rid);
          // 停止成功後、サイドバーに録音ソースを楽観的に追加する。
          // 以降の SSE(source_status) がこの source を既存として status/chunk_count/embedded を
          // パッチし、最終的に ready へ遷移してパネルが消える。
          if (sid) {
            const now = new Date().toISOString();
            const optimistic: Source = {
              id: sid,
              notebook_id: nbId,
              kind: 'recording',
              title: null,
              origin: '録音',
              status: 'parsing',
              error_msg: null,
              bytes: null,
              page_count: null,
              chunk_count: null,
              created_at: now,
              updated_at: now,
            };
            nbStore.upsertSource(optimistic);
          }
        }
      } catch (e) {
        error = e instanceof Error ? e.message : String(e);
      } finally {
        stopping = false;
        resetTransient();
      }
    },
    toggleLiveCaption() {
      liveCaptionEnabled = !liveCaptionEnabled;
    },
    toggleMute(channel) {
      const next = channel === 'mic' ? !micMuted : !systemMuted;
      // サーバへ送信できたときだけ状態を反映する。WS 未接続/送信失敗時に楽観反転すると
      // UI は「ミュート」表示なのにサーバはフレームを STT/変換/埋め込みへ流し続け、
      // 恒久的に乖離する(漏洩)。送れないなら反転せずエラーを出す。確定値はサーバの
      // mute_state エコーで上書きされる(再接続時は resyncMute で再同期)。
      if (!sendMute(channel, next)) {
        error = 'ミュート操作を送信できませんでした(接続待ち/切断中)';
        return;
      }
      if (channel === 'mic') {
        micMuted = next;
      } else {
        systemMuted = next;
      }
    },
  };
}

export const recordingStore = createRecordingStore();

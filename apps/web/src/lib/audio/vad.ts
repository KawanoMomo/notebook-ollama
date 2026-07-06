/** ハンズフリー用の RMS ベース簡易 VAD(spec §4 常時有効)。
 *
 * サーバー側 webrtcvad(既存資産)は使わず、フロント完結でサーバーを
 * ステートレスに保つ(spec 決定 #6)。精度不足なら v2 でサーバー側へ移行。
 * しきい値・ハングオーバーは定数として調整可能(spec §9 リスク)。
 */

export const DEFAULT_RMS_THRESHOLD = 0.012;
export const DEFAULT_HANGOVER_MS = 800;
export const DEFAULT_PREROLL_MS = 300;
export const DEFAULT_MAX_SEGMENT_MS = 30_000;

export interface VadOptions {
  sampleRate: number;
  onSegment: (samples: Float32Array) => void;
  rmsThreshold?: number;
  hangoverMs?: number;
  preRollMs?: number;
  maxSegmentMs?: number;
}

function rms(chunk: Float32Array): number {
  let sum = 0;
  for (let i = 0; i < chunk.length; i++) sum += chunk[i] * chunk[i];
  return Math.sqrt(sum / chunk.length);
}

function concat(parts: Float32Array[]): Float32Array {
  const total = parts.reduce((n, p) => n + p.length, 0);
  const out = new Float32Array(total);
  let o = 0;
  for (const p of parts) {
    out.set(p, o);
    o += p.length;
  }
  return out;
}

export function createVad(opts: VadOptions) {
  const threshold = opts.rmsThreshold ?? DEFAULT_RMS_THRESHOLD;
  const hangoverSamples = ((opts.hangoverMs ?? DEFAULT_HANGOVER_MS) / 1000) * opts.sampleRate;
  const preRollSamples = ((opts.preRollMs ?? DEFAULT_PREROLL_MS) / 1000) * opts.sampleRate;
  const maxSegmentSamples =
    ((opts.maxSegmentMs ?? DEFAULT_MAX_SEGMENT_MS) / 1000) * opts.sampleRate;

  let preRoll: Float32Array[] = [];
  let preRollLen = 0;
  let seg: Float32Array[] = [];
  let segLen = 0;
  let inSpeech = false;
  let silentSamples = 0;

  function emit() {
    if (segLen > 0) opts.onSegment(concat(seg));
    seg = [];
    segLen = 0;
    inSpeech = false;
    silentSamples = 0;
  }

  return {
    push(chunk: Float32Array): void {
      const level = rms(chunk);
      if (!inSpeech) {
        if (level >= threshold) {
          // 発話開始: preRoll を先頭に取り込む
          inSpeech = true;
          silentSamples = 0;
          seg = [...preRoll, chunk];
          segLen = preRollLen + chunk.length;
          preRoll = [];
          preRollLen = 0;
        } else {
          // 無音: preRoll リングを維持
          preRoll.push(chunk);
          preRollLen += chunk.length;
          while (preRollLen > preRollSamples && preRoll.length > 1) {
            preRollLen -= preRoll[0].length;
            preRoll.shift();
          }
        }
        return;
      }
      // 発話中
      seg.push(chunk);
      segLen += chunk.length;
      silentSamples = level < threshold ? silentSamples + chunk.length : 0;
      if (silentSamples >= hangoverSamples || segLen >= maxSegmentSamples) {
        emit();
      }
    },

    flush(): void {
      if (inSpeech) emit();
    },

    reset(): void {
      preRoll = [];
      preRollLen = 0;
      seg = [];
      segLen = 0;
      inSpeech = false;
      silentSamples = 0;
    },
  };
}

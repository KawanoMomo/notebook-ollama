/** Float32 mono PCM → 16kHz mono 16bit WAV(spec §4: クライアント WAV 化)。 */

const TARGET_RATE = 16000;

export function resampleLinear(
  input: Float32Array,
  from: number,
  to: number,
): Float32Array {
  if (from === to) return input;
  const ratio = from / to;
  const outLen = Math.floor(input.length / ratio);
  const out = new Float32Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const pos = i * ratio;
    const i0 = Math.floor(pos);
    const i1 = Math.min(i0 + 1, input.length - 1);
    const frac = pos - i0;
    out[i] = input[i0] * (1 - frac) + input[i1] * frac;
  }
  return out;
}

export function encodeWav16k(samples: Float32Array, sampleRate: number): Blob {
  const data = resampleLinear(samples, sampleRate, TARGET_RATE);
  const buf = new ArrayBuffer(44 + data.length * 2);
  const v = new DataView(buf);
  let o = 0;
  const str = (s: string) => {
    for (const c of s) v.setUint8(o++, c.charCodeAt(0));
  };
  str('RIFF');
  v.setUint32(o, 36 + data.length * 2, true); o += 4;
  str('WAVE');
  str('fmt ');
  v.setUint32(o, 16, true); o += 4;          // fmt chunk size
  v.setUint16(o, 1, true); o += 2;           // PCM
  v.setUint16(o, 1, true); o += 2;           // mono
  v.setUint32(o, TARGET_RATE, true); o += 4; // sample rate
  v.setUint32(o, TARGET_RATE * 2, true); o += 4; // byte rate
  v.setUint16(o, 2, true); o += 2;           // block align
  v.setUint16(o, 16, true); o += 2;          // bits per sample
  str('data');
  v.setUint32(o, data.length * 2, true); o += 4;
  for (let i = 0; i < data.length; i++, o += 2) {
    const s = Math.max(-1, Math.min(1, data[i]));
    v.setInt16(o, Math.round(s < 0 ? s * 0x8000 : s * 0x7fff), true);
  }
  return new Blob([buf], { type: 'audio/wav' });
}

import { describe, expect, it } from 'vitest';
import { encodeWav16k, resampleLinear } from '$lib/audio/wavEncode';

async function header(blob: Blob) {
  const buf = await blob.arrayBuffer();
  const v = new DataView(buf);
  const tag = (o: number) =>
    String.fromCharCode(v.getUint8(o), v.getUint8(o + 1), v.getUint8(o + 2), v.getUint8(o + 3));
  return {
    riff: tag(0),
    wave: tag(8),
    channels: v.getUint16(22, true),
    sampleRate: v.getUint32(24, true),
    bitsPerSample: v.getUint16(34, true),
    dataBytes: v.getUint32(40, true),
    byteLength: buf.byteLength,
    pcm16At: (i: number) => v.getInt16(44 + i * 2, true),
  };
}

describe('encodeWav16k', () => {
  it('16kHz 入力はリサンプルせず正しい WAV ヘッダを書く', async () => {
    const samples = new Float32Array(1600); // 100ms
    samples[0] = 0.5;
    samples[1] = -0.5;
    const h = await header(encodeWav16k(samples, 16000));

    expect(h.riff).toBe('RIFF');
    expect(h.wave).toBe('WAVE');
    expect(h.channels).toBe(1);
    expect(h.sampleRate).toBe(16000);
    expect(h.bitsPerSample).toBe(16);
    expect(h.dataBytes).toBe(1600 * 2);
    expect(h.byteLength).toBe(44 + 1600 * 2);
    expect(h.pcm16At(0)).toBe(Math.round(0.5 * 0x7fff));
    expect(h.pcm16At(1)).toBe(Math.round(-0.5 * 0x8000));
  });

  it('48kHz 入力は 16kHz にダウンサンプルされる', async () => {
    const samples = new Float32Array(4800); // 100ms @48k
    const h = await header(encodeWav16k(samples, 48000));
    expect(h.sampleRate).toBe(16000);
    expect(h.dataBytes).toBe(1600 * 2); // 100ms @16k
  });

  it('振幅は [-1,1] にクランプされる', async () => {
    const samples = new Float32Array([2.0, -2.0]);
    const h = await header(encodeWav16k(samples, 16000));
    expect(h.pcm16At(0)).toBe(0x7fff);
    expect(h.pcm16At(1)).toBe(-0x8000);
  });
});

describe('resampleLinear', () => {
  it('長さが比率どおりになり端点値を保つ', () => {
    const input = new Float32Array([0, 1, 2, 3, 4, 5, 6, 7, 8]); // 9 samples
    const out = resampleLinear(input, 48000, 16000);
    expect(out.length).toBe(3);
    expect(out[0]).toBeCloseTo(0);
    // 中間点は線形補間値
    expect(out[1]).toBeCloseTo(3);
    expect(out[2]).toBeCloseTo(6);
  });
});

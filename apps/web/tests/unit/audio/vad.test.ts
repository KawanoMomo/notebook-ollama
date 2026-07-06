import { beforeEach, describe, expect, it } from 'vitest';
import { createVad } from '$lib/audio/vad';

const SR = 16000;
const CHUNK = 1600; // 100ms

const silence = () => new Float32Array(CHUNK); // RMS 0
const speech = () => new Float32Array(CHUNK).fill(0.1); // RMS 0.1 > 0.012

describe('createVad', () => {
  let segments: Float32Array[];
  let vad: ReturnType<typeof createVad>;

  beforeEach(() => {
    segments = [];
    vad = createVad({ sampleRate: SR, onSegment: (s) => segments.push(s) });
  });

  it('無音のみでは区間を出さない', () => {
    for (let i = 0; i < 20; i++) vad.push(silence());
    expect(segments).toHaveLength(0);
  });

  it('発話 → 800ms 無音で 1 区間確定(preRoll 込み)', () => {
    for (let i = 0; i < 5; i++) vad.push(silence()); // preRoll 素材
    for (let i = 0; i < 10; i++) vad.push(speech()); // 1000ms 発話
    for (let i = 0; i < 8; i++) vad.push(silence()); // 800ms 無音 → 確定
    expect(segments).toHaveLength(1);
    // preRoll 300ms(4800) + 発話 1000ms(16000) + hangover 800ms(12800)
    expect(segments[0].length).toBe(4800 + 16000 + 12800);
  });

  it('発話が 30s に達したら強制分割する', () => {
    // 100ms チャンク × 320 = 32s の連続発話
    for (let i = 0; i < 320; i++) vad.push(speech());
    expect(segments.length).toBeGreaterThanOrEqual(1);
    // 各区間は maxSegmentMs(30s = 480000 サンプル)以下
    for (const s of segments) expect(s.length).toBeLessThanOrEqual(480000);
  });

  it('flush() は発話中の現バッファで確定する', () => {
    for (let i = 0; i < 3; i++) vad.push(speech());
    expect(segments).toHaveLength(0);
    vad.flush();
    expect(segments).toHaveLength(1);
  });

  it('reset() 後は状態を持ち越さない', () => {
    for (let i = 0; i < 3; i++) vad.push(speech());
    vad.reset();
    vad.flush();
    expect(segments).toHaveLength(0);
  });
});

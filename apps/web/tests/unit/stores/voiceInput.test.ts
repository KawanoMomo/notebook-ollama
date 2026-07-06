import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createVoiceInputStore } from '$lib/stores/voiceInput.svelte';

type OnChunk = (samples: Float32Array, sampleRate: number) => void;

function makeDeps() {
  let onChunk: OnChunk | null = null;
  const stop = vi.fn();
  const capture = vi.fn(async (cb: OnChunk) => {
    onChunk = cb;
    return { stop };
  });
  const transcribe = vi.fn(async (_blob: Blob) => ({ text: '認識結果', duration_ms: 100 }));
  return {
    capture,
    transcribe,
    stop,
    feed(ms: number, amp = 0.1) {
      const n = (16000 * ms) / 1000;
      onChunk?.(new Float32Array(n).fill(amp), 16000);
    },
  };
}

describe('voiceInput store — PTT', () => {
  let deps: ReturnType<typeof makeDeps>;
  let store: ReturnType<typeof createVoiceInputStore>;
  let texts: string[];
  let errors: string[];

  beforeEach(() => {
    deps = makeDeps();
    texts = [];
    errors = [];
    store = createVoiceInputStore({ capture: deps.capture, api: { transcribe: deps.transcribe } });
    store.setCallbacks({ onText: (t) => texts.push(t), onError: (m) => errors.push(m) });
  });

  it('pressStart → tapCancel はキャプチャを破棄し transcribe しない', async () => {
    store.pttPressStart();
    await vi.waitFor(() => expect(deps.capture).toHaveBeenCalled());
    store.pttTapCancel();
    expect(deps.stop).toHaveBeenCalled();
    expect(deps.transcribe).not.toHaveBeenCalled();
    expect(store.status).toBe('idle');
  });

  it('pressStart → holdStart → holdEnd で認識テキストが onText に届く', async () => {
    store.pttPressStart();
    await vi.waitFor(() => expect(deps.capture).toHaveBeenCalled());
    store.pttHoldStart();
    expect(store.status).toBe('recording');
    deps.feed(500);
    await store.pttHoldEnd();
    expect(deps.transcribe).toHaveBeenCalledTimes(1);
    expect(texts).toEqual(['認識結果']);
    expect(store.status).toBe('idle');
  });

  it('空の認識結果は onText を呼ばず onError を呼ぶ', async () => {
    deps.transcribe.mockResolvedValueOnce({ text: '', duration_ms: 100 });
    store.pttPressStart();
    await vi.waitFor(() => expect(deps.capture).toHaveBeenCalled());
    store.pttHoldStart();
    deps.feed(500);
    await store.pttHoldEnd();
    expect(texts).toEqual([]);
    expect(errors).toHaveLength(1);
  });

  it('transcribe 失敗は onError に伝わり idle へ戻る', async () => {
    deps.transcribe.mockRejectedValueOnce(new Error('503'));
    store.pttPressStart();
    await vi.waitFor(() => expect(deps.capture).toHaveBeenCalled());
    store.pttHoldStart();
    deps.feed(500);
    await store.pttHoldEnd();
    expect(errors).toHaveLength(1);
    expect(store.status).toBe('idle');
  });
});

describe('voiceInput store — ハンズフリー', () => {
  let deps: ReturnType<typeof makeDeps>;
  let store: ReturnType<typeof createVoiceInputStore>;
  let texts: string[];
  let errors: string[];

  beforeEach(() => {
    deps = makeDeps();
    texts = [];
    errors = [];
    store = createVoiceInputStore({ capture: deps.capture, api: { transcribe: deps.transcribe } });
    store.setCallbacks({ onText: (t) => texts.push(t), onError: (m) => errors.push(m) });
  });

  async function speakOneUtterance() {
    deps.feed(1000);      // 発話 1s
    deps.feed(900, 0);    // 無音 900ms > hangover 800ms → 区間確定
  }

  it('toggle でオン、発話区間ごとに transcribe され onText が届く', async () => {
    await store.handsFreeToggle();
    expect(store.status).toBe('handsfree');
    await speakOneUtterance();
    await vi.waitFor(() => expect(texts).toEqual(['認識結果']));
    await store.handsFreeToggle();
    expect(store.status).toBe('idle');
    expect(deps.stop).toHaveBeenCalled();
  });

  it('POST は直列化される(先行が解決するまで次を送らない)', async () => {
    let release!: (v: { text: string; duration_ms: number }) => void;
    deps.transcribe.mockImplementationOnce(
      () => new Promise((res) => { release = res; }),
    );
    await store.handsFreeToggle();
    await speakOneUtterance(); // 1 区間目(pending のまま)
    await speakOneUtterance(); // 2 区間目
    expect(deps.transcribe).toHaveBeenCalledTimes(1); // 2 件目はキュー待ち
    release({ text: '一件目', duration_ms: 100 });
    await vi.waitFor(() => expect(deps.transcribe).toHaveBeenCalledTimes(2));
  });

  it('許可待ち中にオフへトグルされたら遅延解決したキャプチャを即停止する', async () => {
    let resolveCapture!: (m: { stop: typeof deps.stop }) => void;
    deps.capture.mockImplementationOnce(
      () => new Promise<{ stop: typeof deps.stop }>((res) => { resolveCapture = res; }),
    );
    const turningOn = store.handsFreeToggle(); // getUserMedia 許可プロンプト待ち相当(await しない)
    await store.handsFreeToggle();             // 待ち中にオフへトグル
    expect(store.status).toBe('idle');
    resolveCapture({ stop: deps.stop });       // 遅延解決
    await turningOn;
    expect(deps.stop).toHaveBeenCalled();      // 解決済みキャプチャは即停止(リーク防止)
    expect(store.status).toBe('idle');
  });

  it('3 連続失敗で自動オフ + onError', async () => {
    deps.transcribe.mockRejectedValue(new Error('503'));
    await store.handsFreeToggle();
    await speakOneUtterance();
    await vi.waitFor(() => expect(deps.transcribe).toHaveBeenCalledTimes(1));
    await speakOneUtterance();
    await vi.waitFor(() => expect(deps.transcribe).toHaveBeenCalledTimes(2));
    await speakOneUtterance();
    await vi.waitFor(() => expect(store.status).toBe('idle')); // 自動オフ
    expect(errors.length).toBeGreaterThanOrEqual(1);
    expect(deps.stop).toHaveBeenCalled();
  });
});

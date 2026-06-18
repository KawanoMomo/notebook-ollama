import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { createConversationStore } from '$lib/stores/conversation.svelte';
import type { ChatEvent } from '$lib/api/chat';
import type { Conversation } from '$lib/api/types';

// notify は Notification API を触るため無効化する
vi.mock('$lib/utils/notifications', () => ({
  notify: vi.fn(),
  requestPermissionOnce: vi.fn(),
}));

const conv: Conversation = {
  id: 'c1',
  notebook_id: 'nb1',
  title: null,
  created_at: '2026-06-19T00:00:00Z',
  updated_at: '2026-06-19T00:00:00Z',
};

function makeApi(events: ChatEvent[], opts: { hold?: boolean } = {}) {
  return {
    createConversation: vi.fn().mockResolvedValue(conv),
    listMessages: vi.fn().mockResolvedValue([]),
    sendMessage: vi.fn(function* () {
      for (const ev of events) yield ev;
      // hold=true のときはここで返らず、呼び側が手動で進める想定では使わない
    }),
  };
}

describe('conversation store', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('ping/token 受信で lastBeatAt が更新され warning は立たない', async () => {
    const events: ChatEvent[] = [
      { kind: 'ping' },
      { kind: 'token', text: 'こん' },
      { kind: 'token', text: 'にちは' },
      {
        kind: 'done',
        answer: 'こんにちは',
        citations: [],
        model_used: 'qwen2.5:14b',
        dropped_history: 0,
      },
    ];
    const store = createConversationStore(makeApi(events) as never);
    await store.send('nb1', '質問');
    // done 後は finally でリセットされ streaming=false, warning=null
    expect(store.streaming).toBe(false);
    expect(store.warning).toBeNull();
    expect(store.messages.at(-1)?.content).toBe('こんにちは');
  });

  it('60s ビート途絶で warning が立つ(ストリーム保留中)', async () => {
    // sendMessage を「token 1回 → 以降保留」にして streaming 中に時間を進める
    let resolveGen!: () => void;
    const gate = new Promise<void>((r) => (resolveGen = r));
    const api = {
      createConversation: vi.fn().mockResolvedValue(conv),
      listMessages: vi.fn().mockResolvedValue([]),
      sendMessage: vi.fn(async function* () {
        yield { kind: 'token', text: 'A' } as ChatEvent;
        await gate; // ここで保留 = ストリーム継続中
      }),
    };
    const store = createConversationStore(api as never);
    const p = store.send('nb1', '質問');
    // streaming 中: 監視タイマーを 65s 進める
    await vi.advanceTimersByTimeAsync(65_000);
    expect(store.streaming).toBe(true);
    expect(store.warning).toBe('Ollamaが応答していない可能性があります');
    // ストリームを閉じて後始末
    resolveGen();
    await vi.advanceTimersByTimeAsync(0);
    await p;
    expect(store.warning).toBeNull();
  });

  it('cancel() で abort され streaming/監視が止まる', async () => {
    let resolveGen!: () => void;
    const gate = new Promise<void>((r) => (resolveGen = r));
    const api = {
      createConversation: vi.fn().mockResolvedValue(conv),
      listMessages: vi.fn().mockResolvedValue([]),
      sendMessage: vi.fn(async function* (
        _nb: string,
        _cid: string,
        _content: string,
        signal?: AbortSignal,
      ) {
        yield { kind: 'token', text: 'A' } as ChatEvent;
        await gate;
        if (signal?.aborted) return;
      }),
    };
    const store = createConversationStore(api as never);
    const p = store.send('nb1', '質問');
    await vi.advanceTimersByTimeAsync(0);
    expect(store.streaming).toBe(true);
    store.cancel();
    resolveGen();
    await p;
    expect(store.streaming).toBe(false);
    expect(store.warning).toBeNull();
  });
});

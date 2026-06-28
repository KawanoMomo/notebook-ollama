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

  it('renameSpeakerInSource が同一 source の引用 location の話者ラベルだけ置換する', async () => {
    const cite = (
      n: number,
      source_id: string,
      location: string,
    ) => ({
      n,
      chunk_id: `chunk-${n}`,
      source_id,
      source_title: 't',
      location,
      url_or_path: null,
      snippet: 's',
      audio_source_id: source_id,
      audio_start_ms: 0,
    });
    const seeded = [
      {
        id: 'm1',
        conversation_id: 'c1',
        role: 'assistant',
        content: 'a',
        model: null,
        created_at: '2026-06-19T00:00:00Z',
        citations: [
          cite(1, 'src-A', '相手1 00:12:30'), // 置換対象
          cite(2, 'src-A', '相手1'), // 話者のみ -> 置換対象
          cite(3, 'src-A', '相手10 00:01:00'), // 前方一致だが別ラベル -> 不変
          cite(4, 'src-B', '相手1 00:00:05'), // 別 source -> 不変
          cite(5, 'src-A', 'あなた 00:00:01'), // 別話者 -> 不変
        ],
      },
    ];
    const api = {
      createConversation: vi.fn().mockResolvedValue(conv),
      listMessages: vi.fn().mockResolvedValue(seeded),
      sendMessage: vi.fn(),
    };
    const store = createConversationStore(api as never);
    await store.load('nb1', 'c1');

    store.renameSpeakerInSource('src-A', '相手1', '田中さん');

    const locs = store.messages[0].citations.map((c) => c.location);
    expect(locs).toEqual([
      '田中さん 00:12:30', // 置換
      '田中さん', // 置換(話者のみ)
      '相手10 00:01:00', // 前方一致誤マッチ回避 -> 不変
      '相手1 00:00:05', // 別 source -> 不変
      'あなた 00:00:01', // 別話者 -> 不変
    ]);
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

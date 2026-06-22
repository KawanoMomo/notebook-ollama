import { describe, expect, it, vi, beforeEach } from 'vitest';
import { createRecordingStore } from '$lib/stores/recording.svelte';
import type { CurrentNotebookStore } from '$lib/stores/currentNotebook.svelte';
import type { Source } from '$lib/api/types';

// jsdom には WebSocket が未定義のため最小スタブを用意する
class FakeWS {
  static OPEN = 1;
  static instances: FakeWS[] = [];
  readyState = 1;
  sent: string[] = [];
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  constructor() {
    FakeWS.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {}
  /** サーバ→クライアントのメッセージ受信を模倣 */
  emit(msg: unknown) {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
}

beforeEach(() => {
  FakeWS.instances = [];
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS;
});

function makeApi() {
  return {
    start: vi.fn().mockResolvedValue({
      recording_id: 'r1',
      source_id: 's1',
      status: 'recording',
      live_caption: true,
    }),
    stop: vi.fn().mockResolvedValue({
      recording_id: 'r1',
      source_id: 's1',
      status: 'processing',
      paths: {},
    }),
  };
}

const noopNbStore = {
  upsertSource: () => {},
} as unknown as CurrentNotebookStore;

describe('recording store', () => {
  it('stop 成功時に楽観的 Source を nbStore へ upsert する', async () => {
    const api = {
      start: vi.fn().mockResolvedValue({
        recording_id: 'r1',
        source_id: 's1',
        status: 'recording',
        live_caption: false,
      }),
      stop: vi.fn().mockResolvedValue({
        recording_id: 'r1',
        source_id: 's1',
        status: 'processing',
        paths: {},
      }),
    };
    const upserts: Source[] = [];
    const nbStore = {
      upsertSource: (s: Source) => upserts.push(s),
    } as unknown as CurrentNotebookStore;

    const store = createRecordingStore(api as never, nbStore);
    await store.start('nb1');
    await store.stop();

    expect(upserts).toHaveLength(1);
    expect(upserts[0]).toMatchObject({
      id: 's1',
      notebook_id: 'nb1',
      kind: 'recording',
      status: 'parsing',
      origin: '録音',
    });
  });

  it('api.stop 失敗時は upsert せず error が立つ', async () => {
    const api = {
      start: vi.fn().mockResolvedValue({
        recording_id: 'r1',
        source_id: 's1',
        status: 'recording',
        live_caption: false,
      }),
      stop: vi.fn().mockRejectedValue(new Error('boom')),
    };
    const upserts: Source[] = [];
    const nbStore = {
      upsertSource: (s: Source) => upserts.push(s),
    } as unknown as CurrentNotebookStore;

    const store = createRecordingStore(api as never, nbStore);
    await store.start('nb1');
    await store.stop();

    expect(upserts).toHaveLength(0);
    expect(store.error).toBe('boom');
  });

  it('toggleMute はミュート状態を切り替え WS へ mute コマンドを送る', async () => {
    const store = createRecordingStore(makeApi() as never, noopNbStore);
    await store.start('nb1');
    const ws = FakeWS.instances.at(-1)!;

    expect(store.micMuted).toBe(false);

    store.toggleMute('mic');
    expect(store.micMuted).toBe(true);
    expect(store.systemMuted).toBe(false);
    expect(JSON.parse(ws.sent.at(-1)!)).toEqual({
      type: 'mute',
      channel: 'mic',
      muted: true,
    });

    store.toggleMute('mic');
    expect(store.micMuted).toBe(false);
    expect(JSON.parse(ws.sent.at(-1)!)).toEqual({
      type: 'mute',
      channel: 'mic',
      muted: false,
    });

    store.toggleMute('system');
    expect(store.systemMuted).toBe(true);
    expect(JSON.parse(ws.sent.at(-1)!)).toEqual({
      type: 'mute',
      channel: 'system',
      muted: true,
    });
  });

  it('サーバの mute_state でミュート状態が同期される', async () => {
    const store = createRecordingStore(makeApi() as never, noopNbStore);
    await store.start('nb1');
    const ws = FakeWS.instances.at(-1)!;

    ws.emit({ type: 'mute_state', channel: 'system', muted: true });
    expect(store.systemMuted).toBe(true);
    expect(store.micMuted).toBe(false);

    ws.emit({ type: 'mute_state', channel: 'system', muted: false });
    expect(store.systemMuted).toBe(false);
  });

  it('ミュート中チャンネルの新規字幕は追加しない(過去分は残す)', async () => {
    const store = createRecordingStore(makeApi() as never, noopNbStore);
    await store.start('nb1');
    const ws = FakeWS.instances.at(-1)!;

    // ミュート前の字幕は表示される
    ws.emit({ type: 'caption', id: 'c1', label: '相手', text: 'こんにちは', start_ms: 0, is_final: true });
    expect(store.captions).toHaveLength(1);

    // system をミュート
    store.toggleMute('system');

    // ミュート中に届いた相手(system)の字幕は破棄される
    ws.emit({ type: 'caption', id: 'c2', label: '相手', text: '無視される', start_ms: 1000, is_final: true });
    expect(store.captions).toHaveLength(1);
    expect(store.captions[0].id).toBe('c1');

    // 一方、ミュートしていない あなた(mic)の字幕は通る
    ws.emit({ type: 'caption', id: 'c3', label: 'あなた', text: '通る', start_ms: 1500, is_final: true });
    expect(store.captions).toHaveLength(2);
    expect(store.captions.at(-1)!.id).toBe('c3');
  });
});

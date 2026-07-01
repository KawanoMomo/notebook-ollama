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
  onopen: (() => void) | null = null;
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
    expect(store.stopping).toBe(false);
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

  it('WS未OPEN時の toggleMute は状態を反転せずエラーを立てる(乖離防止)', async () => {
    const store = createRecordingStore(makeApi() as never, noopNbStore);
    await store.start('nb1');
    const ws = FakeWS.instances.at(-1)!;
    // 接続が CONNECTING / 切断中の状況を模倣
    ws.readyState = 0;

    store.toggleMute('mic');
    expect(store.micMuted).toBe(false); // 反転していない
    expect(ws.sent).toHaveLength(0); // コマンドも送られていない
    expect(store.error).toContain('送信できませんでした');
  });

  it('再接続(onopen)時に現在のミュート状態をサーバへ再送する', async () => {
    const store = createRecordingStore(makeApi() as never, noopNbStore);
    await store.start('nb1');
    const ws = FakeWS.instances.at(-1)!;
    // mic をミュート(OPEN なので成功)
    store.toggleMute('mic');
    expect(store.micMuted).toBe(true);
    ws.sent.length = 0; // 以降の再送だけを観測

    // 再接続確立を模倣: onopen が両チャンネルの現在状態を再送する
    ws.onopen?.();
    const sent = ws.sent.map((s) => JSON.parse(s));
    expect(sent).toContainEqual({ type: 'mute', channel: 'mic', muted: true });
    expect(sent).toContainEqual({ type: 'mute', channel: 'system', muted: false });
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

  it('start は API 応答前に starting=true、応答後に recording=true / starting=false', async () => {
    let resolveStart!: (v: unknown) => void;
    const api = {
      start: vi.fn().mockReturnValue(
        new Promise((res) => {
          resolveStart = res;
        }),
      ),
      stop: vi.fn(),
    };
    const store = createRecordingStore(api as never, noopNbStore);

    const p = store.start('nb1');
    // await 前 = API 応答前: optimistic に starting が立ち、recording はまだ false
    expect(store.starting).toBe(true);
    expect(store.recording).toBe(false);

    resolveStart({
      recording_id: 'r1',
      source_id: 's1',
      status: 'recording',
      live_caption: false,
    });
    await p;
    expect(store.starting).toBe(false);
    expect(store.recording).toBe(true);
  });

  it('api.start 失敗時は starting=false に戻り recording は false のまま(例外は伝播)', async () => {
    const api = {
      start: vi.fn().mockRejectedValue(new Error('mic busy')),
      stop: vi.fn(),
    };
    const store = createRecordingStore(api as never, noopNbStore);
    await expect(store.start('nb1')).rejects.toThrow('mic busy');
    expect(store.starting).toBe(false);
    expect(store.recording).toBe(false);
  });

  it('stop は API 応答前に stopping=true、完了後に stopping=false', async () => {
    let resolveStop!: (v: unknown) => void;
    const api = {
      start: vi.fn().mockResolvedValue({
        recording_id: 'r1',
        source_id: 's1',
        status: 'recording',
        live_caption: false,
      }),
      stop: vi.fn().mockReturnValue(
        new Promise((res) => {
          resolveStop = res;
        }),
      ),
    };
    const store = createRecordingStore(api as never, noopNbStore);
    await store.start('nb1');

    const p = store.stop();
    expect(store.stopping).toBe(true);

    resolveStop({ recording_id: 'r1', source_id: 's1', status: 'processing', paths: {} });
    await p;
    expect(store.stopping).toBe(false);
    expect(store.recording).toBe(false);
  });

  it('starting 中の二重 start は no-op', async () => {
    let resolveStart!: (v: unknown) => void;
    const api = {
      start: vi.fn().mockReturnValue(
        new Promise((res) => {
          resolveStart = res;
        }),
      ),
      stop: vi.fn(),
    };
    const store = createRecordingStore(api as never, noopNbStore);
    const p = store.start('nb1');
    void store.start('nb1'); // 二重呼び出し
    expect(api.start).toHaveBeenCalledTimes(1);
    resolveStart({
      recording_id: 'r1',
      source_id: 's1',
      status: 'recording',
      live_caption: false,
    });
    await p;
  });
});

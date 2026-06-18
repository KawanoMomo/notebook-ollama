import { describe, expect, it, vi, beforeEach } from 'vitest';
import { createRecordingStore } from '$lib/stores/recording.svelte';
import type { CurrentNotebookStore } from '$lib/stores/currentNotebook.svelte';
import type { Source } from '$lib/api/types';

// jsdom には WebSocket が未定義のため最小スタブを用意する
class FakeWS {
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  close() {}
}

beforeEach(() => {
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS;
});

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
});

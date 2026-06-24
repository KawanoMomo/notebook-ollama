import { afterEach, describe, expect, it, vi } from 'vitest';
import { createCurrentNotebookStore } from '$lib/stores/currentNotebook.svelte';
import type { Source } from '$lib/api/types';

const fakeNotebook = {
  id: 'nb1',
  name: 'N',
  description: null,
  default_model: null,
  created_at: 't',
  updated_at: 't',
  source_count: 0,
};

function makeSource(id: string, overrides: Partial<Source> = {}): Source {
  return {
    id,
    notebook_id: 'nb1',
    kind: 'markdown',
    title: id,
    origin: null,
    status: 'ready',
    error_msg: null,
    bytes: null,
    page_count: null,
    chunk_count: 1,
    has_audio: false,
    embedded: 1,
    duration_ms: null,
    created_at: 't',
    updated_at: 't',
    ...overrides,
  };
}

function makeStore(sources: Source[]) {
  const nbApi = { get: vi.fn().mockResolvedValue(fakeNotebook) } as any;
  const srcApi = { list: vi.fn().mockResolvedValue(sources) } as any;
  return { store: createCurrentNotebookStore(nbApi, srcApi), nbApi, srcApi };
}

describe('currentNotebookStore — default-all-selected', () => {
  afterEach(() => vi.restoreAllMocks());

  it('selects every source after load()', async () => {
    const sources = [makeSource('a'), makeSource('b'), makeSource('c')];
    const { store } = makeStore(sources);
    await store.load('nb1');
    expect(store.selectedSourceIds.size).toBe(3);
    expect(store.selectedSourceIds.has('a')).toBe(true);
    expect(store.selectedSourceIds.has('b')).toBe(true);
    expect(store.selectedSourceIds.has('c')).toBe(true);
  });

  it('upsertSource adds a new source to the selection automatically', async () => {
    const { store } = makeStore([makeSource('a')]);
    await store.load('nb1');
    expect(store.selectedSourceIds.size).toBe(1);
    store.upsertSource(makeSource('z'));
    expect(store.selectedSourceIds.has('z')).toBe(true);
    expect(store.selectedSourceIds.size).toBe(2);
  });

  it('upsertSource for an existing source does not change selection state', async () => {
    const { store } = makeStore([makeSource('a'), makeSource('b')]);
    await store.load('nb1');
    store.toggleSelected('a'); // deselect a
    expect(store.selectedSourceIds.has('a')).toBe(false);
    // 既存の a を別タイトルで upsert → 選択状態は変更されない
    store.upsertSource(makeSource('a', { title: 'a-renamed' }));
    expect(store.selectedSourceIds.has('a')).toBe(false);
  });

  it('selectAll() picks every loaded source', async () => {
    const { store } = makeStore([makeSource('a'), makeSource('b')]);
    await store.load('nb1');
    store.clearSelection();
    expect(store.selectedSourceIds.size).toBe(0);
    store.selectAll();
    expect(store.selectedSourceIds.size).toBe(2);
  });

  it('selectAll(ids) only selects the given subset (for filter-mode all-select)', async () => {
    const { store } = makeStore([makeSource('a'), makeSource('b'), makeSource('c')]);
    await store.load('nb1');
    store.clearSelection();
    store.selectAll(['a', 'c']);
    expect(store.selectedSourceIds.has('a')).toBe(true);
    expect(store.selectedSourceIds.has('b')).toBe(false);
    expect(store.selectedSourceIds.has('c')).toBe(true);
  });

  it('load() resets selection (no persistence across notebook switches)', async () => {
    const { store, srcApi } = makeStore([makeSource('a'), makeSource('b')]);
    await store.load('nb1');
    store.toggleSelected('a');
    expect(store.selectedSourceIds.has('a')).toBe(false);
    // 別ノートをロード
    srcApi.list.mockResolvedValueOnce([makeSource('x'), makeSource('y')]);
    await store.load('nb1');
    // 新しいソース集合に対して全選択(永続化なし)
    expect(store.selectedSourceIds.has('x')).toBe(true);
    expect(store.selectedSourceIds.has('y')).toBe(true);
    expect(store.selectedSourceIds.has('a')).toBe(false);
  });
});

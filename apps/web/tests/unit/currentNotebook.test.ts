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

function makeStore(sources: Source[], links: any[] = []) {
  const nbApi = { get: vi.fn().mockResolvedValue(fakeNotebook) } as any;
  const srcApi = { list: vi.fn().mockResolvedValue(sources) } as any;
  const lnkApi = {
    list: vi.fn().mockResolvedValue(links),
    setParent: vi.fn(),
    removeParent: vi.fn(),
  } as any;
  return { store: createCurrentNotebookStore(nbApi, srcApi, lnkApi), nbApi, srcApi, lnkApi };
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

function makeJobSource(overrides: Partial<Source> = {}): Source {
  return {
    id: 'src1',
    notebook_id: 'nb1',
    kind: 'pdf',
    title: '設計書.pdf',
    origin: null,
    status: 'ready',
    error_msg: null,
    bytes: null,
    page_count: null,
    chunk_count: null,
    created_at: 't',
    updated_at: 't',
    ...overrides,
  };
}

describe('currentNotebookStore.activeJobs', () => {
  it('ready のみのソースでは空配列', () => {
    const store = createCurrentNotebookStore();
    store.upsertSource(makeJobSource());
    expect(store.activeJobs).toEqual([]);
  });

  it('取り込み中 (parsing/embedding 等) は ingest ジョブになる', () => {
    const store = createCurrentNotebookStore();
    store.upsertSource(makeJobSource({ status: 'parsing' }));
    expect(store.activeJobs).toEqual([
      { sourceId: 'src1', kind: 'ingest', label: '設計書.pdf: 取り込み中' },
    ]);
  });

  it('summary_status/adr_status が generating なら各ジョブになる(同一ソースで複数可)', () => {
    const store = createCurrentNotebookStore();
    store.upsertSource(
      makeJobSource({ summary_status: 'generating', adr_status: 'generating' }),
    );
    expect(store.activeJobs).toEqual([
      { sourceId: 'src1', kind: 'summary', label: '設計書.pdf: 要約生成中' },
      { sourceId: 'src1', kind: 'adr', label: '設計書.pdf: ADR生成中' },
    ]);
  });

  it('error / skipped は進行中として扱わない', () => {
    const store = createCurrentNotebookStore();
    store.upsertSource(
      makeJobSource({
        status: 'error',
        summary_status: 'error',
        adr_status: 'skipped',
      }),
    );
    expect(store.activeJobs).toEqual([]);
  });

  it('title が無ければ origin、それも無ければ「ソース」をラベルに使う', () => {
    const store = createCurrentNotebookStore();
    store.upsertSource(
      makeJobSource({ title: null, origin: '録音', status: 'parsing' }),
    );
    expect(store.activeJobs[0].label).toBe('録音: 取り込み中');
  });
});

describe('currentNotebookStore.links', () => {
  afterEach(() => vi.restoreAllMocks());

  it('load() は links を並行取得してストアに反映する', async () => {
    const links = [
      {
        id: 'l1',
        notebook_id: 'nb1',
        parent_source_id: 'a',
        child_source_id: 'b',
        relation: 'manual' as const,
        meta: null,
        created_at: 't',
      },
    ];
    const { store, lnkApi } = makeStore([makeSource('a'), makeSource('b')], links);
    await store.load('nb1');
    expect(lnkApi.list).toHaveBeenCalledWith('nb1');
    expect(store.links).toEqual(links);
    // ソース表示は壊れていない
    expect(store.sources).toHaveLength(2);
    expect(store.error).toBeNull();
  });

  it('linksApi.list が reject しても links=[] に degrade し、ソース表示は継続する', async () => {
    const { store, lnkApi } = makeStore([makeSource('a'), makeSource('b')]);
    lnkApi.list.mockRejectedValueOnce(new Error('links unavailable'));
    await store.load('nb1');
    expect(store.links).toEqual([]);
    expect(store.sources).toHaveLength(2);
    expect(store.error).toBeNull();
  });
});

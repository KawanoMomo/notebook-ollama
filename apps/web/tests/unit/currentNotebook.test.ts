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

  it('図解析フェーズは件数と割合を出す (status は chunking のまま動かないため)', () => {
    const store = createCurrentNotebookStore();
    store.upsertSource(
      makeJobSource({ status: 'chunking', figures_done: 953, figures_total: 3427 }),
    );
    expect(store.activeJobs[0].label).toBe('設計書.pdf: 図を解析中 953/3427（27%）');
  });

  it('図解析が完了したら通常の「取り込み中」に戻る', () => {
    const store = createCurrentNotebookStore();
    store.upsertSource(
      makeJobSource({ status: 'chunking', figures_done: 10, figures_total: 10 }),
    );
    expect(store.activeJobs[0].label).toBe('設計書.pdf: 取り込み中');
  });

  it('図が0件のPDFでは図解析ラベルを出さない', () => {
    const store = createCurrentNotebookStore();
    store.upsertSource(
      makeJobSource({ status: 'chunking', figures_done: 0, figures_total: 0 }),
    );
    expect(store.activeJobs[0].label).toBe('設計書.pdf: 取り込み中');
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

function makeLink(childId: string, parentId: string) {
  return {
    id: `link-${childId}-${parentId}`,
    notebook_id: 'nb1',
    parent_source_id: parentId,
    child_source_id: childId,
    relation: 'manual' as const,
    meta: null,
    created_at: 't',
  };
}

describe('currentNotebookStore.setParent / removeParent', () => {
  afterEach(() => vi.restoreAllMocks());

  it('setParent が linksApi.setParent を呼び links を更新する', async () => {
    const { store, lnkApi } = makeStore([makeSource('a'), makeSource('b')]);
    await store.load('nb1');
    const newLinks = [makeLink('b', 'a')];
    lnkApi.setParent.mockResolvedValueOnce(newLinks[0]);
    lnkApi.list.mockResolvedValueOnce(newLinks);
    await store.setParent('b', 'a');
    expect(lnkApi.setParent).toHaveBeenCalledWith('nb1', 'b', 'a');
    expect(store.links).toEqual(newLinks);
  });

  it('removeParent が linksApi.removeParent を呼び links を更新する', async () => {
    const initial = [makeLink('b', 'a')];
    const { store, lnkApi } = makeStore([makeSource('a'), makeSource('b')], initial);
    await store.load('nb1');
    expect(store.links).toEqual(initial);
    lnkApi.removeParent.mockResolvedValueOnce(undefined);
    lnkApi.list.mockResolvedValueOnce([]);
    await store.removeParent('b');
    expect(lnkApi.removeParent).toHaveBeenCalledWith('nb1', 'b');
    expect(store.links).toEqual([]);
  });

  it('setParent の API 例外は呼び出し元へ伝播し、links は変更されない', async () => {
    const initial = [makeLink('b', 'a')];
    const { store, lnkApi } = makeStore(
      [makeSource('a'), makeSource('b'), makeSource('c')],
      initial,
    );
    await store.load('nb1');
    lnkApi.setParent.mockRejectedValueOnce(new Error('循環リンクは作成できません'));
    await expect(store.setParent('a', 'b')).rejects.toThrow('循環リンクは作成できません');
    expect(store.links).toEqual(initial);
  });

  it('古い list 応答が新しい状態を上書きしない(レースガード)', async () => {
    const { store, lnkApi } = makeStore([
      makeSource('a'),
      makeSource('b'),
      makeSource('c'),
    ]);
    await store.load('nb1');

    const linksA = [makeLink('b', 'a')];
    const linksB = [makeLink('b', 'a'), makeLink('c', 'a')];
    let resolveA!: (v: typeof linksA) => void;
    lnkApi.setParent.mockResolvedValue(makeLink('x', 'y'));
    lnkApi.list
      // mutation A の再取得: 保留(後で手動 resolve)
      .mockImplementationOnce(() => new Promise((r) => (resolveA = r)))
      // mutation B の再取得: 即時 resolve
      .mockResolvedValueOnce(linksB);

    // mutation A を発行し、list 呼び出し(保留)まで進める
    const pA = store.setParent('b', 'a');
    await Promise.resolve();
    await Promise.resolve();
    expect(lnkApi.list).toHaveBeenCalledTimes(2); // load + A

    // mutation B を発行して完了させる → links = B の結果
    await store.setParent('c', 'a');
    expect(store.links).toEqual(linksB);

    // 古い A の応答を解決しても B の結果を上書きしない
    resolveA(linksA);
    await pA;
    expect(store.links).toEqual(linksB);
  });
});

describe('currentNotebookStore.refreshSources', () => {
  afterEach(() => vi.restoreAllMocks());

  it('sources と links を API から再取得して反映する(終端 source_status イベント用)', async () => {
    // 録音の optimistic source を模す: title=null のプレースホルダ
    const { store, srcApi, lnkApi } = makeStore([
      makeSource('rec1', { title: null, origin: '録音', status: 'parsing' }),
    ]);
    await store.load('nb1');
    expect(store.sources[0].title).toBeNull();

    const readySources = [
      makeSource('rec1', {
        title: 'eval-deck.pdf 発表 2026-07-08',
        origin: '録音',
        status: 'ready',
      }),
    ];
    const readyLinks = [makeLink('rec1', 'deck1')];
    srcApi.list.mockResolvedValueOnce(readySources);
    lnkApi.list.mockResolvedValueOnce(readyLinks);

    await store.refreshSources();

    expect(srcApi.list).toHaveBeenCalledWith('nb1');
    expect(lnkApi.list).toHaveBeenCalledWith('nb1');
    expect(store.sources).toEqual(readySources);
    expect(store.links).toEqual(readyLinks);
  });

  it('実行中に load() でノートが切り替わると、古い refreshSources 応答は破棄される', async () => {
    const { store, srcApi } = makeStore([makeSource('a', { title: null })]);
    await store.load('nb1');

    // refreshSources() を発行するが、srcApi.list を保留状態にしておく
    let resolveStale!: (v: Source[]) => void;
    srcApi.list.mockImplementationOnce(() => new Promise((r) => (resolveStale = r)));
    const stalePromise = store.refreshSources();
    await Promise.resolve();
    await Promise.resolve();

    // 保留中に別ノートへ切り替わる(=世代が進む)
    const freshSources = [makeSource('x', { title: 'x' })];
    srcApi.list.mockResolvedValueOnce(freshSources);
    await store.load('nb2');
    expect(store.sources).toEqual(freshSources);

    // 保留していた古い refreshSources 応答を今解決しても、load() 後の状態を上書きしない
    resolveStale([makeSource('a', { title: 'STALE-SHOULD-NOT-APPEAR' })]);
    await stalePromise;
    expect(store.sources).toEqual(freshSources);
  });

  it('ノート未ロード(notebook=null)では no-op で API を呼ばない', async () => {
    const { store, srcApi, lnkApi } = makeStore([makeSource('a')]);
    await store.refreshSources();
    expect(srcApi.list).not.toHaveBeenCalled();
    expect(lnkApi.list).not.toHaveBeenCalled();
  });
});

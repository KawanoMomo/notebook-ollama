/**
 * SourceViewer の引用・ビューア強化(Task 11)。
 * 仕様: docs/specs/2026-07-06-presentation-mode-design.md §7, task-11-brief.md。
 *
 * (a) 録音チャンク側: 表示中チャンクの source が親リンクを持ち chunk.page があるとき、
 *     「親: {親タイトル} の p.{page} で発言」ラベルと「該当スライド(p.{page})を表示」
 *     ボタンが出る。押下でビューア内に SlideView(スタブ)がトグル表示される。
 * (b) スライド資料側: kind∈{pdf,pptx} を全文表示するとき slide-utterances を取得し、
 *     ページごとに <details> で件数表示する。
 *
 * SlideView は pdf.js/canvas に依存するため PresentationView.test.ts と同じ方式で
 * スタブに差し替える(実描画は evaluator の実機検証で担保)。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import type { ChunkDetail, SourceContent } from '$lib/api/source_outline';
import type { Source, SourceLink, SlideUtterancePage } from '$lib/api/types';

// vi.hoisted で巻き上げ(PresentationView.test.ts と同じパターン)。
const sourceDetail = vi.hoisted(() => ({
  getChunk: vi.fn(),
  getSourceContent: vi.fn(),
  renameSpeaker: vi.fn(),
}));
vi.mock('$lib/api/source_outline', () => ({ sourceDetailApi: sourceDetail }));

const links = vi.hoisted(() => ({
  setParent: vi.fn(),
  removeParent: vi.fn(),
  list: vi.fn(),
  slideUtterances: vi.fn(),
}));
vi.mock('$lib/api/links', () => ({ linksApi: links }));

const notebookStore = vi.hoisted(() => ({
  sources: [] as Source[],
  links: [] as SourceLink[],
}));
vi.mock('$lib/stores/currentNotebook.svelte', () => ({
  currentNotebookStore: notebookStore,
}));

const sourcesApiMock = vi.hoisted(() => ({
  listAssets: vi.fn(),
}));
vi.mock('$lib/api/sources', () => ({ sourcesApi: sourcesApiMock }));

const featuresStoreMock = vi.hoisted(() => ({
  flags: [] as { id: string; enabled: boolean }[],
}));
vi.mock('$lib/stores/features.svelte', () => ({ featuresStore: featuresStoreMock }));

// SlideView は canvas/pdf.js を使うため差し替え(PresentationView.test.ts と同じ)。
vi.mock('$lib/components/SlideView.svelte', async () => {
  const Stub = (await import('./stubs/SlideViewStub.svelte')).default;
  return { default: Stub };
});

import SourceViewer from '$lib/components/SourceViewer.svelte';

function makeSource(overrides: Partial<Source> = {}): Source {
  return {
    id: 'src1',
    notebook_id: 'nb1',
    kind: 'recording',
    title: null,
    origin: null,
    status: 'ready',
    error_msg: null,
    bytes: null,
    page_count: null,
    chunk_count: 1,
    created_at: 't',
    updated_at: 't',
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  notebookStore.sources = [];
  notebookStore.links = [];
  featuresStoreMock.flags = [];
  sourcesApiMock.listAssets.mockResolvedValue({ assets: [] });
});
afterEach(() => cleanup());

describe('SourceViewer — 録音チャンクの親リンク表記+該当スライド表示', () => {
  it('親リンク+page ありで親表記とボタンが出て、押下で SlideView がトグル表示される', async () => {
    const chunk: ChunkDetail = {
      id: 'chunk1',
      source_id: 'rec1',
      page: 3,
      heading_path: null,
      text: '発言内容です',
      start_ms: 1000,
      end_ms: 2000,
      speaker: 'あなた',
    };
    sourceDetail.getChunk.mockResolvedValue(chunk);

    notebookStore.sources = [
      makeSource({ id: 'rec1', kind: 'recording', title: '録音1' }),
      makeSource({ id: 'parent1', kind: 'pdf', title: '資料A' }),
    ];
    notebookStore.links = [
      {
        id: 'link1',
        notebook_id: 'nb1',
        parent_source_id: 'parent1',
        child_source_id: 'rec1',
        relation: 'presentation',
        meta: null,
        created_at: 't',
      },
    ];

    render(SourceViewer, {
      props: { notebookId: 'nb1', selectedChunkId: 'chunk1', selectedSourceId: 'rec1' },
    });

    await waitFor(() => {
      expect(screen.getByText('親: 資料A の p.3 で発言')).toBeTruthy();
    });
    const btn = screen.getByRole('button', { name: '該当スライド(p.3)を表示' });
    expect(btn).toBeTruthy();

    // トグル: 押下で SlideView スタブが表示され、本文テキストは消える
    expect(screen.getByText('発言内容です')).toBeTruthy();
    expect(screen.queryByTestId('slide-stub')).toBeNull();
    await fireEvent.click(btn);
    expect(screen.getByTestId('slide-stub')).toBeTruthy();
    expect(screen.queryByText('発言内容です')).toBeNull();

    // もう一度押すとテキストに戻る
    await fireEvent.click(btn);
    expect(screen.queryByTestId('slide-stub')).toBeNull();
    expect(screen.getByText('発言内容です')).toBeTruthy();
  });

  it('親リンクが無いチャンクでは親表記もボタンも出ない(既存表示は不変)', async () => {
    const chunk: ChunkDetail = {
      id: 'chunk2',
      source_id: 'rec1',
      page: null,
      heading_path: null,
      text: '発言2',
      start_ms: 0,
      end_ms: 500,
      speaker: '相手1',
    };
    sourceDetail.getChunk.mockResolvedValue(chunk);
    notebookStore.sources = [makeSource({ id: 'rec1', kind: 'recording' })];
    notebookStore.links = [];

    render(SourceViewer, {
      props: { notebookId: 'nb1', selectedChunkId: 'chunk2', selectedSourceId: 'rec1' },
    });

    await waitFor(() => {
      expect(screen.getByText('発言2')).toBeTruthy();
    });
    expect(screen.queryByText(/^親: /)).toBeNull();
    expect(screen.queryByRole('button', { name: /該当スライド/ })).toBeNull();
  });
});

describe('SourceViewer — スライド資料側のページ別発言の逆引き', () => {
  it('kind=pdf の全文表示で slide-utterances を取得し、ページごとに <details> と件数を表示する', async () => {
    const content: SourceContent = {
      kind: 'document',
      sections: [{ heading_path: null, page: 1, text: 'スライド本文' }],
    };
    sourceDetail.getSourceContent.mockResolvedValue(content);

    const groups: SlideUtterancePage[] = [
      {
        page: 1,
        items: [
          {
            child_source_id: 'rec1',
            child_title: '録音1',
            chunk_id: 'c1',
            start_ms: 0,
            end_ms: 1000,
            speaker: 'あなた',
            text: 'page1の発言',
          },
        ],
      },
      {
        page: 2,
        items: [
          {
            child_source_id: 'rec1',
            child_title: '録音1',
            chunk_id: 'c2',
            start_ms: 1000,
            end_ms: 2000,
            speaker: '相手1',
            text: 'page2の発言A',
          },
          {
            child_source_id: 'rec2',
            child_title: '録音2',
            chunk_id: 'c3',
            start_ms: 0,
            end_ms: 800,
            speaker: 'あなた',
            text: 'page2の発言B',
          },
        ],
      },
    ];
    links.slideUtterances.mockResolvedValue(groups);

    notebookStore.sources = [makeSource({ id: 'parent1', kind: 'pdf', title: '資料A' })];
    notebookStore.links = [];

    const { container } = render(SourceViewer, {
      props: { notebookId: 'nb1', selectedChunkId: null, selectedSourceId: 'parent1' },
    });

    await waitFor(() => {
      expect(container.querySelectorAll('details').length).toBe(2);
    });
    expect(links.slideUtterances).toHaveBeenCalledWith('nb1', 'parent1');
    expect(screen.getByText('p.1 — 1件')).toBeTruthy();
    expect(screen.getByText('p.2 — 2件')).toBeTruthy();
  });

  it('録音ソースの全文表示では slide-utterances を取得しない', async () => {
    const content: SourceContent = {
      kind: 'recording',
      segments: [{ ord: 0, text: 'セグメント', start_ms: 0, end_ms: 500, speaker: 'あなた' }],
    };
    sourceDetail.getSourceContent.mockResolvedValue(content);
    notebookStore.sources = [makeSource({ id: 'rec1', kind: 'recording' })];

    render(SourceViewer, {
      props: { notebookId: 'nb1', selectedChunkId: null, selectedSourceId: 'rec1' },
    });

    await waitFor(() => {
      expect(screen.getByText('セグメント')).toBeTruthy();
    });
    expect(links.slideUtterances).not.toHaveBeenCalled();
  });
});

describe('SourceViewer — 全文表示(チャンク未選択)時の表アセットHTML置換', () => {
  it('table-figure-rag 有効 + ページ一致の表アセットがあれば、Markdown snippet を HTML に置換して描画する', async () => {
    const content: SourceContent = {
      kind: 'document',
      sections: [{ heading_path: null, page: 1, text: '前文\n| 品名 | 数量 |\n後文' }],
    };
    sourceDetail.getSourceContent.mockResolvedValue(content);
    sourcesApiMock.listAssets.mockResolvedValue({
      assets: [
        {
          id: 'a1',
          source_id: 'parent1',
          chunk_id: null,
          kind: 'table',
          page: 1,
          bbox_json: null,
          html: '<table><tr><td>品名</td><td>数量</td></tr></table>',
          md_snippet: '| 品名 | 数量 |',
          image_path: null,
          created_at: 't',
        },
      ],
    });
    featuresStoreMock.flags = [{ id: 'table-figure-rag', enabled: true }];
    notebookStore.sources = [makeSource({ id: 'parent1', kind: 'pdf', title: '資料A' })];

    const { container } = render(SourceViewer, {
      props: { notebookId: 'nb1', selectedChunkId: null, selectedSourceId: 'parent1' },
    });

    await waitFor(() => {
      expect(container.querySelector('table')).toBeTruthy();
    });
    expect(screen.queryByText(/\| 品名 \| 数量 \|/)).toBeNull();
  });

  it('table-figure-rag が無効なら、表アセットが存在してもプレーンテキストのまま表示する', async () => {
    const content: SourceContent = {
      kind: 'document',
      sections: [{ heading_path: null, page: 1, text: '前文\n| 品名 | 数量 |\n後文' }],
    };
    sourceDetail.getSourceContent.mockResolvedValue(content);
    featuresStoreMock.flags = [];
    notebookStore.sources = [makeSource({ id: 'parent1', kind: 'pdf', title: '資料A' })];

    const { container } = render(SourceViewer, {
      props: { notebookId: 'nb1', selectedChunkId: null, selectedSourceId: 'parent1' },
    });

    await waitFor(() => {
      expect(screen.getByText(/品名/)).toBeTruthy();
    });
    expect(container.querySelector('table')).toBeNull();
    expect(sourcesApiMock.listAssets).not.toHaveBeenCalled();
  });

  it('一致する表アセットが無ければプレーンテキストのままフォールバックする', async () => {
    const content: SourceContent = {
      kind: 'document',
      sections: [{ heading_path: null, page: 1, text: '表なし本文' }],
    };
    sourceDetail.getSourceContent.mockResolvedValue(content);
    sourcesApiMock.listAssets.mockResolvedValue({ assets: [] });
    featuresStoreMock.flags = [{ id: 'table-figure-rag', enabled: true }];
    notebookStore.sources = [makeSource({ id: 'parent1', kind: 'pdf', title: '資料A' })];

    const { container } = render(SourceViewer, {
      props: { notebookId: 'nb1', selectedChunkId: null, selectedSourceId: 'parent1' },
    });

    await waitFor(() => {
      expect(screen.getByText('表なし本文')).toBeTruthy();
    });
    expect(container.querySelector('table')).toBeNull();
  });
});

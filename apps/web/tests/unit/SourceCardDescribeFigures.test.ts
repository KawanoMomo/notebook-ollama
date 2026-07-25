/**
 * SourceCard の「図を解析」(describeFigures) ボタン。
 * 仕様: task-8-brief.md, Task 8。
 *
 * - pdf かつ status===ready かつ onDescribeFigures が渡されているときのみ表示
 *   (reingest と異なり error では表示しない: 完了したチャンク/アセットが無いため)
 * - クリックで onDescribeFigures コールバックが発火
 * - フラグ判定(isTableFigureRagEnabled)は呼び出し元(SourcesPanel)の責務なので、
 *   SourceCard 自体は onDescribeFigures の有無だけで表示可否を決める(dumb presentational)。
 *
 * フィクスチャは SourceCardReingest.test.ts の render パターンをコピー。
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import SourceCard from '$lib/components/SourceCard.svelte';
import type { Source } from '$lib/api/types';

afterEach(() => cleanup());

function makeSource(overrides: Partial<Source> = {}): Source {
  return {
    id: 'src1',
    notebook_id: 'nb1',
    kind: 'pdf',
    title: '資料A',
    origin: 'doc.pdf',
    status: 'ready',
    error_msg: null,
    bytes: 2048,
    page_count: 12,
    chunk_count: 5,
    has_audio: false,
    embedded: 5,
    duration_ms: null,
    created_at: 't',
    updated_at: 't',
    ...overrides,
  };
}

function baseProps(source: Source, extra: Record<string, unknown> = {}) {
  return {
    source,
    selected: false,
    onToggle: vi.fn(),
    onSelect: vi.fn(),
    onRetry: vi.fn(),
    onReembed: vi.fn(),
    onDelete: vi.fn(),
    ...extra,
  };
}

describe('SourceCard — 図を解析', () => {
  it('pdf + ready + onDescribeFigures ありで表示され、クリックでコールバックが発火する', async () => {
    const onDescribeFigures = vi.fn();
    render(SourceCard, baseProps(makeSource({ status: 'ready' }), { onDescribeFigures }));
    const btn = screen.getByLabelText('図を解析') as HTMLButtonElement;
    expect(btn.tagName).toBe('BUTTON');
    await fireEvent.click(btn);
    expect(onDescribeFigures).toHaveBeenCalledTimes(1);
  });

  it('onDescribeFigures が渡されないときは表示しない(フラグOFF相当)', () => {
    render(SourceCard, baseProps(makeSource({ status: 'ready' })));
    expect(screen.queryByLabelText('図を解析')).toBeNull();
  });

  it('pdf以外(markdown)では onDescribeFigures があっても表示しない', () => {
    const onDescribeFigures = vi.fn();
    render(
      SourceCard,
      baseProps(makeSource({ kind: 'markdown', status: 'ready' }), { onDescribeFigures }),
    );
    expect(screen.queryByLabelText('図を解析')).toBeNull();
  });

  it('error ステータスでは表示しない(reingestと異なり ready のみ)', () => {
    const onDescribeFigures = vi.fn();
    render(
      SourceCard,
      baseProps(makeSource({ status: 'error' }), { onDescribeFigures }),
    );
    expect(screen.queryByLabelText('図を解析')).toBeNull();
  });

  it('未完了ステータス(embedding等)では表示しない', () => {
    const onDescribeFigures = vi.fn();
    render(
      SourceCard,
      baseProps(makeSource({ status: 'embedding' }), { onDescribeFigures }),
    );
    expect(screen.queryByLabelText('図を解析')).toBeNull();
  });
});

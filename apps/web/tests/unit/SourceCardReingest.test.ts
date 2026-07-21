/**
 * SourceCard の「表・図を再解析」(reingest) ボタン。
 * 仕様: task-10-brief.md, Task 10。
 *
 * - pdf かつ status∈{ready,error} かつ onReingest が渡されているときのみ表示
 * - クリックで onReingest コールバックが発火
 * - フラグ判定(isTableFigureRagEnabled)は呼び出し元(SourcesPanel)の責務なので、
 *   SourceCard 自体は onReingest の有無だけで表示可否を決める(dumb presentational)。
 *
 * フィクスチャは既存 tests/unit/SourceCardPresentation.test.ts の render パターンをコピー。
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

describe('SourceCard — 表・図を再解析', () => {
  it('pdf + ready + onReingest ありで表示され、クリックでコールバックが発火する', async () => {
    const onReingest = vi.fn();
    render(SourceCard, baseProps(makeSource({ status: 'ready' }), { onReingest }));
    const btn = screen.getByLabelText('表・図を再解析') as HTMLButtonElement;
    expect(btn.tagName).toBe('BUTTON');
    await fireEvent.click(btn);
    expect(onReingest).toHaveBeenCalledTimes(1);
  });

  it('pdf + error + onReingest ありでも表示される', () => {
    const onReingest = vi.fn();
    render(SourceCard, baseProps(makeSource({ status: 'error' }), { onReingest }));
    expect(screen.getByLabelText('表・図を再解析')).toBeTruthy();
  });

  it('onReingest が渡されないときは表示しない(フラグOFF相当)', () => {
    render(SourceCard, baseProps(makeSource({ status: 'ready' })));
    expect(screen.queryByLabelText('表・図を再解析')).toBeNull();
  });

  it('pdf以外(markdown)では onReingest があっても表示しない', () => {
    const onReingest = vi.fn();
    render(
      SourceCard,
      baseProps(makeSource({ kind: 'markdown', status: 'ready' }), { onReingest }),
    );
    expect(screen.queryByLabelText('表・図を再解析')).toBeNull();
  });

  it('未完了ステータス(embedding等)では表示しない', () => {
    const onReingest = vi.fn();
    render(
      SourceCard,
      baseProps(makeSource({ status: 'embedding' }), { onReingest }),
    );
    expect(screen.queryByLabelText('表・図を再解析')).toBeNull();
  });
});

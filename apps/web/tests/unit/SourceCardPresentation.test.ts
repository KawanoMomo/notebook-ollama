/**
 * SourceCard の「発表を開始」ボタン。
 * 仕様: docs/specs/2026-07-06-presentation-mode-design.md, Task 9 brief.
 *
 * - pdf/pptx ソースのみ表示 (markdown 等では非表示)
 * - pptx かつ has_slides=false は disabled + ツールチップ
 * - クリックで onStartPresentation コールバックが発火
 * - 既存アクション行の aria-label(変換を停止 等)は影響を受けない
 *
 * フィクスチャは既存 tests/unit/SourceCard.test.ts の render パターンをコピーし、
 * has_slides を付与した。
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
    origin: 'slide.pdf',
    status: 'ready',
    error_msg: null,
    bytes: 2048,
    page_count: 12,
    chunk_count: 5,
    has_audio: false,
    has_slides: true,
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

describe('SourceCard — 発表を開始', () => {
  it('pdf(has_slides:true) で「発表を開始」が表示され、クリックでコールバックが発火する', async () => {
    const onStartPresentation = vi.fn();
    render(
      SourceCard,
      baseProps(makeSource({ kind: 'pdf', has_slides: true }), { onStartPresentation }),
    );
    const btn = screen.getByLabelText('発表を開始') as HTMLButtonElement;
    expect(btn.tagName).toBe('BUTTON');
    expect(btn.disabled).toBe(false);
    await fireEvent.click(btn);
    expect(onStartPresentation).toHaveBeenCalledTimes(1);
  });

  it('pptx + has_slides:false は disabled になり、案内ツールチップの title を持つ', () => {
    const onStartPresentation = vi.fn();
    render(
      SourceCard,
      baseProps(makeSource({ kind: 'pptx', has_slides: false }), { onStartPresentation }),
    );
    const btn = screen.getByLabelText('発表を開始') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.title).toBe('PDFに書き出して取り込むと発表できます');
  });

  it('markdown ソースでは「発表を開始」を表示しない', () => {
    const onStartPresentation = vi.fn();
    render(
      SourceCard,
      baseProps(makeSource({ kind: 'markdown', has_slides: undefined }), {
        onStartPresentation,
      }),
    );
    expect(screen.queryByLabelText('発表を開始')).toBeNull();
  });

  it('録音カードでは非表示のまま、既存の「変換を停止」aria-label は引き続き機能する(退行ガード)', async () => {
    const onStopConversion = vi.fn();
    const onStartPresentation = vi.fn();
    render(
      SourceCard,
      baseProps(
        makeSource({
          id: 'rec1',
          kind: 'recording',
          status: 'embedding',
          has_slides: undefined,
        }),
        { onStopConversion, onStartPresentation },
      ),
    );
    expect(screen.queryByLabelText('発表を開始')).toBeNull();
    const stop = screen.getByLabelText('変換を停止');
    await fireEvent.click(stop);
    expect(onStopConversion).toHaveBeenCalledTimes(1);
    // 他の既存アクションの aria-label も健在であること
    expect(screen.getByLabelText('削除')).toBeTruthy();
    expect(screen.getByLabelText('名前を編集')).toBeTruthy();
  });
});

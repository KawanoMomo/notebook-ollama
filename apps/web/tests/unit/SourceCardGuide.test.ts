/**
 * SourceCard のソースガイド(要約表示)領域。
 * 仕様: docs/specs/2026-06-25-source-guide-design.md §4
 *
 * - タイトルクリックで展開(デフォルト open)
 * - generating / ready / error の 3 状態
 * - 再生成ボタンが onSummarize を呼ぶ
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
    kind: 'markdown',
    title: '設計仕様書',
    origin: 'spec.md',
    status: 'ready',
    error_msg: null,
    bytes: 1234,
    page_count: 10,
    chunk_count: 5,
    has_audio: false,
    embedded: 5,
    duration_ms: null,
    summary: null,
    summary_status: null,
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
    // ガイド領域は onGuideToggle が渡されると表示されるため、本テスト群では既定で渡す
    onGuideToggle: vi.fn(),
    ...extra,
  };
}

describe('SourceCard — ソースガイド領域', () => {
  it('renders the guide skeleton when summary_status="generating"', () => {
    render(
      SourceCard,
      baseProps(
        makeSource({ summary: null, summary_status: 'generating' }),
        { guideExpanded: true },
      ),
    );
    expect(screen.getByText(/要約を生成中/)).toBeDefined();
  });

  it('renders the summary text when summary_status="ready"', () => {
    render(
      SourceCard,
      baseProps(
        makeSource({
          summary: 'この文書はソースガイド機能の設計仕様をまとめたものです。',
          summary_status: 'ready',
        }),
        { guideExpanded: true },
      ),
    );
    expect(screen.getByText(/ソースガイド機能の設計仕様/)).toBeDefined();
  });

  it('renders an error message + retry button when summary_status="error"', () => {
    const onSummarize = vi.fn();
    render(
      SourceCard,
      baseProps(
        makeSource({ summary: null, summary_status: 'error' }),
        { guideExpanded: true, onSummarize },
      ),
    );
    expect(screen.getByText(/生成に失敗しました/)).toBeDefined();
  });

  it('does not show guide body when collapsed (guideExpanded=false)', () => {
    render(
      SourceCard,
      baseProps(
        makeSource({
          summary: '本文',
          summary_status: 'ready',
        }),
        { guideExpanded: false },
      ),
    );
    // ヘッダー("ソースガイド")は表示されるが、本文「本文」は表示されない
    expect(screen.getByText(/ソースガイド/)).toBeDefined();
    expect(screen.queryByText('本文')).toBeNull();
  });

  it('clicking the guide header toggles guideExpanded via onGuideToggle', async () => {
    const onGuideToggle = vi.fn();
    render(
      SourceCard,
      baseProps(
        makeSource({ summary: 'x', summary_status: 'ready' }),
        { guideExpanded: false, onGuideToggle },
      ),
    );
    const header = screen.getByRole('button', { name: /ソースガイドを開閉/ });
    await fireEvent.click(header);
    expect(onGuideToggle).toHaveBeenCalledTimes(1);
  });

  it('clicking the regenerate button calls onSummarize', async () => {
    const onSummarize = vi.fn();
    render(
      SourceCard,
      baseProps(
        makeSource({ summary: 'x', summary_status: 'ready' }),
        { guideExpanded: true, onSummarize },
      ),
    );
    const btn = screen.getByRole('button', { name: /要約を再生成/ });
    await fireEvent.click(btn);
    expect(onSummarize).toHaveBeenCalledTimes(1);
  });

  // 再生成ボタンのガード(ADR ボタンと同一パターン)。
  // 変換未完了のソースで「確実に失敗する要約」を起動させない(2026-07-04 実機フィードバック)。
  it('disables the regenerate button and prompts conversion when chunk_count is 0', () => {
    const onSummarize = vi.fn();
    render(
      SourceCard,
      baseProps(
        makeSource({ chunk_count: 0, summary: null, summary_status: null }),
        { guideExpanded: true, onSummarize },
      ),
    );
    const btn = screen.getByRole('button', {
      name: /変換が完了してから要約できます/,
    }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('disables the regenerate button when source status is not ready', () => {
    const onSummarize = vi.fn();
    render(
      SourceCard,
      baseProps(
        makeSource({ status: 'error', summary: null, summary_status: null }),
        { guideExpanded: true, onSummarize },
      ),
    );
    const btn = screen.getByRole('button', {
      name: /変換が完了してから要約できます/,
    }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('disables the regenerate button while summary is generating', () => {
    const onSummarize = vi.fn();
    render(
      SourceCard,
      baseProps(
        makeSource({ summary: null, summary_status: 'generating' }),
        { guideExpanded: true, onSummarize },
      ),
    );
    const btn = screen.getByRole('button', {
      name: /要約を生成中/,
    }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  // 生成中の中断スイッチ(2026-07-04 実機フィードバック)
  it('shows a cancel button while generating and clicking it calls onSummaryCancel', async () => {
    const onSummaryCancel = vi.fn();
    render(
      SourceCard,
      baseProps(
        makeSource({ summary: null, summary_status: 'generating' }),
        { guideExpanded: true, onSummaryCancel },
      ),
    );
    const btn = screen.getByRole('button', { name: /要約を中断/ });
    await fireEvent.click(btn);
    expect(onSummaryCancel).toHaveBeenCalledTimes(1);
  });

  it('does not show the cancel button when not generating', () => {
    const onSummaryCancel = vi.fn();
    render(
      SourceCard,
      baseProps(
        makeSource({ summary: 'x', summary_status: 'ready' }),
        { guideExpanded: true, onSummaryCancel },
      ),
    );
    expect(screen.queryByRole('button', { name: /要約を中断/ })).toBeNull();
  });
});

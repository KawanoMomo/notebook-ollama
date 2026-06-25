/**
 * SourceCard の ADR ボタンと ADR セクション。
 * 設計: docs/specs/2026-06-26-meeting-adr-templates.md
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
    kind: 'recording',
    title: '議事録 A',
    origin: '録音',
    status: 'ready',
    error_msg: null,
    bytes: null,
    page_count: null,
    chunk_count: 8,
    has_audio: true,
    embedded: 8,
    duration_ms: 600000,
    summary: null,
    summary_status: null,
    adr_draft: null,
    adr_status: null,
    adr_template: null,
    adr_confidence: null,
    adr_generated_at: null,
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
    onGuideToggle: vi.fn(),  // ガイドを開いた状態で ADR 領域が見える
    onSummarize: vi.fn(),
    onGenerateAdr: vi.fn(),
    guideExpanded: true,
    ...extra,
  };
}

describe('SourceCard — ADR ボタン', () => {
  it('shows the ADR button when onGenerateAdr handler is provided', () => {
    render(SourceCard, baseProps(makeSource()));
    expect(screen.getByLabelText(/ADR を抽出|ADR を再抽出/)).toBeDefined();
  });

  it('clicking the ADR button calls onGenerateAdr', async () => {
    const onGenerateAdr = vi.fn();
    render(SourceCard, baseProps(makeSource(), { onGenerateAdr }));
    const btn = screen.getByLabelText(/ADR/);
    await fireEvent.click(btn);
    expect(onGenerateAdr).toHaveBeenCalledTimes(1);
  });

  it('disables the ADR button when chunk_count is 0 (no content)', () => {
    render(SourceCard, baseProps(makeSource({ chunk_count: 0 })));
    const btn = screen.getByLabelText(/ADR/) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('disables the ADR button while adr_status==="generating"', () => {
    render(
      SourceCard,
      baseProps(makeSource({ adr_status: 'generating' })),
    );
    const btn = screen.getByLabelText(/ADR/) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });
});

describe('SourceCard — ADR セクション本体', () => {
  it('renders nothing for ADR section when adr_status is null', () => {
    const { container } = render(SourceCard, baseProps(makeSource()));
    expect(container.querySelector('.adr-section')).toBeNull();
  });

  it('renders skeleton + label when adr_status==="generating"', () => {
    render(SourceCard, baseProps(makeSource({ adr_status: 'generating' })));
    expect(screen.getByText(/ADR を抽出中/)).toBeDefined();
  });

  it('renders the Markdown draft when adr_status==="ready"', () => {
    const draft = '# ADR-001\n\n## Context\n背景の説明';
    render(
      SourceCard,
      baseProps(
        makeSource({
          adr_status: 'ready',
          adr_draft: draft,
          adr_template: 'madr',
          adr_confidence: 'high',
        }),
      ),
    );
    // Markdown ソースをそのまま <pre> に表示する設計
    expect(screen.getByText(/背景の説明/)).toBeDefined();
    expect(screen.getByText(/madr/i)).toBeDefined();
  });

  it('renders the skipped message when adr_status==="skipped"', () => {
    render(SourceCard, baseProps(makeSource({ adr_status: 'skipped' })));
    expect(screen.getByText(/Architecture Decision が検出されません/)).toBeDefined();
  });

  it('renders an error message when adr_status==="error"', () => {
    render(SourceCard, baseProps(makeSource({ adr_status: 'error' })));
    expect(screen.getByText(/ADR 抽出に失敗/)).toBeDefined();
  });
});

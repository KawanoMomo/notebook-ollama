/**
 * events ストアの SSE ハンドラが summary_status / adr_status を
 * currentNotebookStore へ patch することを検証する。
 * 設計: docs/specs/2026-07-02-job-status-bar-optimistic-ui-design.md
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Source } from '$lib/api/types';
import type { SourceStatusEvent } from '$lib/api/events';

// openNotebookEvents をモックし、ハンドラ(onEvent)を捕捉して手動でイベントを流す
let capturedOnEvent: ((ev: SourceStatusEvent) => void) | null = null;
vi.mock('$lib/api/events', () => ({
  openNotebookEvents: vi.fn(
    (_id: string, onEvent: (ev: SourceStatusEvent) => void) => {
      capturedOnEvent = onEvent;
      return () => {};
    },
  ),
}));

// モック定義後に import する(hoisting のため dynamic import を使う)
const { eventsStore } = await import('$lib/stores/events.svelte');
const { currentNotebookStore } = await import('$lib/stores/currentNotebook.svelte');

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
    created_at: 't',
    updated_at: 't',
    summary_status: 'generating',
    adr_status: 'generating',
    ...overrides,
  };
}

beforeEach(() => {
  capturedOnEvent = null;
  currentNotebookStore.clear();
});

afterEach(() => {
  eventsStore.stop();
  currentNotebookStore.clear();
});

describe('events store — summary_status / adr_status patch', () => {
  it('ペイロードに summary_status があればストアの source へ反映する', () => {
    currentNotebookStore.upsertSource(makeSource());
    eventsStore.start('nb1');
    capturedOnEvent!({
      source_id: 'src1',
      status: 'ready',
      summary_status: 'ready',
    });
    expect(currentNotebookStore.sources[0].summary_status).toBe('ready');
    // adr_status はペイロードに無いので既存値を維持
    expect(currentNotebookStore.sources[0].adr_status).toBe('generating');
  });

  it('ペイロードに adr_status があればストアの source へ反映する', () => {
    currentNotebookStore.upsertSource(makeSource());
    eventsStore.start('nb1');
    capturedOnEvent!({
      source_id: 'src1',
      status: 'ready',
      adr_status: 'ready',
    });
    expect(currentNotebookStore.sources[0].adr_status).toBe('ready');
    expect(currentNotebookStore.sources[0].summary_status).toBe('generating');
  });

  it('どちらも無いペイロードでは両フィールドの既存値を維持する', () => {
    currentNotebookStore.upsertSource(makeSource());
    eventsStore.start('nb1');
    capturedOnEvent!({ source_id: 'src1', status: 'ready' });
    expect(currentNotebookStore.sources[0].summary_status).toBe('generating');
    expect(currentNotebookStore.sources[0].adr_status).toBe('generating');
  });

  it('ready イベントの summary 本文をストアへ反映する(再取得なしで表示できる)', () => {
    currentNotebookStore.upsertSource(makeSource());
    eventsStore.start('nb1');
    capturedOnEvent!({
      source_id: 'src1',
      status: 'ready',
      summary_status: 'ready',
      summary: '要約本文です。',
    });
    expect(currentNotebookStore.sources[0].summary_status).toBe('ready');
    expect(currentNotebookStore.sources[0].summary).toBe('要約本文です。');
  });

  it('ready イベントの adr_draft / adr_template / adr_confidence を反映する', () => {
    currentNotebookStore.upsertSource(makeSource());
    eventsStore.start('nb1');
    capturedOnEvent!({
      source_id: 'src1',
      status: 'ready',
      adr_status: 'ready',
      adr_draft: '# ADR: 案 A の採用',
      adr_template: 'madr',
      adr_confidence: 'high',
    });
    expect(currentNotebookStore.sources[0].adr_status).toBe('ready');
    expect(currentNotebookStore.sources[0].adr_draft).toBe('# ADR: 案 A の採用');
    expect(currentNotebookStore.sources[0].adr_template).toBe('madr');
    expect(currentNotebookStore.sources[0].adr_confidence).toBe('high');
  });

  it('summary 本文が無いペイロードでは既存の summary を維持する', () => {
    currentNotebookStore.upsertSource(makeSource({ summary: '既存の要約' }));
    eventsStore.start('nb1');
    capturedOnEvent!({ source_id: 'src1', status: 'ready', summary_status: 'ready' });
    expect(currentNotebookStore.sources[0].summary).toBe('既存の要約');
  });
});

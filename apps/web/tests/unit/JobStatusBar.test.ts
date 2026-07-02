/**
 * JobStatusBar — 進行中ジョブの永続表示バー。
 * 設計: docs/specs/2026-07-02-job-status-bar-optimistic-ui-design.md
 */
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/svelte';
import JobStatusBar from '$lib/components/JobStatusBar.svelte';

afterEach(() => cleanup());

describe('JobStatusBar', () => {
  it('ジョブ0件では何も描画しない', () => {
    const { container } = render(JobStatusBar, { jobs: [] });
    expect(container.querySelector('.jobbar')).toBeNull();
  });

  it('ジョブごとにラベルを1行ずつ表示する', () => {
    render(JobStatusBar, {
      jobs: [
        { sourceId: 's1', kind: 'summary', label: '議事録.docx: 要約生成中' },
        { sourceId: 's1', kind: 'adr', label: '議事録.docx: ADR生成中' },
      ],
    });
    expect(screen.getByText('議事録.docx: 要約生成中')).toBeDefined();
    expect(screen.getByText('議事録.docx: ADR生成中')).toBeDefined();
  });

  it('step があれば step_label と進捗%を併記する', () => {
    render(JobStatusBar, {
      jobs: [
        {
          sourceId: 's1',
          kind: 'ingest',
          label: '録音: 取り込み中',
          step: { step: 'stt', step_label: '文字起こし中', progress: 0.4 },
        },
      ],
    });
    expect(screen.getByText(/文字起こし中/)).toBeDefined();
    expect(screen.getByText(/40%/)).toBeDefined();
  });

  it('スクリーンリーダー向けに role=status を持つ', () => {
    render(JobStatusBar, {
      jobs: [{ sourceId: 's1', kind: 'summary', label: 'x: 要約生成中' }],
    });
    expect(screen.getByRole('status')).toBeDefined();
  });
});

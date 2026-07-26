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

  // 実機FB 2026-07-26: 図解析は数千件×数秒で数時間規模になるため、
  // 「あと何時間か」が出ないと止まっているのか判断できない。
  it('etaSeconds があれば残り時間目安を時間単位まで丸めて表示する', () => {
    render(JobStatusBar, {
      jobs: [
        {
          sourceId: 's1',
          kind: 'ingest',
          label: '本.pdf: 図を解析中 953/3427（27%）',
          etaSeconds: 11_100, // 3時間5分
        },
      ],
    });
    expect(screen.getByText('残り約3時間5分')).toBeDefined();
  });

  it('etaSeconds が無いジョブには残り時間を出さない', () => {
    render(JobStatusBar, {
      jobs: [{ sourceId: 's1', kind: 'ingest', label: '本.pdf: 取り込み中' }],
    });
    expect(screen.queryByText(/残り約/)).toBeNull();
  });

  it('スクリーンリーダー向けに role=status を持つ', () => {
    render(JobStatusBar, {
      jobs: [{ sourceId: 's1', kind: 'summary', label: 'x: 要約生成中' }],
    });
    expect(screen.getByRole('status')).toBeDefined();
  });
});

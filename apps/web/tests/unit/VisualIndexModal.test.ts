import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

import VisualIndexModal from '$lib/components/VisualIndexModal.svelte';
import type { VisualIndexStatus, VisualUnitStatus } from '$lib/api/visualIndex';

function unitStatus(over: Partial<VisualUnitStatus> = {}): VisualUnitStatus {
  return {
    built: false,
    embedding_model: null,
    built_at: null,
    indexed_sources: 0,
    pending_sources: 0,
    building: false,
    ...over,
  };
}

function makeStatus(over: Partial<VisualIndexStatus> = {}): VisualIndexStatus {
  return {
    extra_available: true,
    index_unit: 'page',
    search_strategy: 'hybrid_rrf',
    units: { page: unitStatus(), tile: unitStatus() },
    ...over,
  };
}

function renderModal(over: Partial<VisualIndexStatus> = {}, props: Record<string, unknown> = {}) {
  return render(VisualIndexModal, {
    props: {
      notebookId: 'nb1',
      status: makeStatus(over),
      progressFor: () => null,
      onBuild: vi.fn(),
      onDelete: vi.fn(),
      onClose: vi.fn(),
      ...props,
    },
  });
}

describe('VisualIndexModal', () => {
  it('両方の索引の行を表示する', () => {
    renderModal();
    expect(screen.getByRole('group', { name: 'ページ索引' })).toBeTruthy();
    expect(screen.getByRole('group', { name: 'タイル索引' })).toBeTruthy();
  });

  it('未構築の行には削除ボタンを出さない', () => {
    renderModal();
    expect(screen.queryByRole('button', { name: 'ページ索引を削除' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'タイル索引を削除' })).toBeNull();
  });

  it('構築済みの行にだけ削除ボタンを出す', () => {
    renderModal({
      units: {
        page: unitStatus({ built: true, embedding_model: 'm', built_at: '2026-07-29T10:00:00Z' }),
        tile: unitStatus(),
      },
    });
    expect(screen.getByRole('button', { name: 'ページ索引を削除' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'タイル索引を削除' })).toBeNull();
  });

  it('構築ボタンは単位を渡して呼ばれる', async () => {
    const onBuild = vi.fn();
    renderModal({}, { onBuild });
    (screen.getByRole('button', { name: 'タイル索引を構築' }) as HTMLButtonElement).click();
    expect(onBuild).toHaveBeenCalledWith('tile');
  });

  it('削除は2段階確認で、行ごとに独立している', async () => {
    const onDelete = vi.fn();
    renderModal(
      {
        units: {
          page: unitStatus({ built: true }),
          tile: unitStatus({ built: true }),
        },
      },
      { onDelete },
    );
    // 生の .click() は @testing-library/svelte の eventWrapper(flushSync)を経由せず、
    // Svelte 5 の状態更新がマイクロタスクで反映される前に次の assertion が走ってしまう。
    // fireEvent 経由(内部で act() -> flushSync)にして同期反映させてから検証する。
    await fireEvent.click(screen.getByRole('button', { name: 'ページ索引を削除' }));
    expect(onDelete).not.toHaveBeenCalled();
    // page 行だけが armed になり、tile 行は元のラベルのまま
    expect(screen.getByRole('button', { name: '本当にページ索引を削除' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'タイル索引を削除' })).toBeTruthy();

    await fireEvent.click(screen.getByRole('button', { name: '本当にページ索引を削除' }));
    expect(onDelete).toHaveBeenCalledWith('page');
  });

  it('「やめる」で armed 状態が解除される', async () => {
    renderModal({ units: { page: unitStatus({ built: true }), tile: unitStatus() } });
    await fireEvent.click(screen.getByRole('button', { name: 'ページ索引を削除' }));
    await fireEvent.click(screen.getByRole('button', { name: 'ページ索引の削除をやめる' }));
    expect(screen.getByRole('button', { name: 'ページ索引を削除' })).toBeTruthy();
  });

  it('構築中の行に進捗と残り時間目安を出す', () => {
    renderModal(
      { units: { page: unitStatus({ building: true }), tile: unitStatus() } },
      { progressFor: (u: string) => (u === 'page' ? { done: 3, total: 10, etaSeconds: 400 } : null) },
    );
    const row = screen.getByRole('group', { name: 'ページ索引' });
    expect(within(row).getByText(/3 \/ 10/)).toBeTruthy();
    expect(within(row).getByText(/残り目安 約7分/)).toBeTruthy();
    // tile 行には進捗が出ない
    const tileRow = screen.getByRole('group', { name: 'タイル索引' });
    expect(within(tileRow).queryByText(/\d+ \/ \d+/)).toBeNull();
  });

  it('60秒未満の ETA は「1分未満」と出す', () => {
    renderModal(
      { units: { page: unitStatus({ building: true }), tile: unitStatus() } },
      { progressFor: () => ({ done: 9, total: 10, etaSeconds: 30 }) },
    );
    expect(screen.getByText(/残り目安 1分未満/)).toBeTruthy();
  });

  it('extra 未導入なら両方の構築ボタンを無効化する', () => {
    renderModal({ extra_available: false });
    expect(
      (screen.getByRole('button', { name: 'ページ索引を構築' }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(
      (screen.getByRole('button', { name: 'タイル索引を構築' }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it('検索に使われている単位を示す', () => {
    renderModal({ index_unit: 'tile' });
    const row = screen.getByRole('group', { name: 'タイル索引' });
    expect(within(row).getByText(/検索に使用中/)).toBeTruthy();
  });
});

describe('VisualIndexModal 構築中の表示', () => {
  it('progress 到着前でも構築中とわかる表示を出す', () => {
    // 回帰テスト: `u.building && progress` の AND だったため、構築開始から
    // 最初の progress イベントまでが完全に無表示だった (issue #28 M2)。
    // タイル索引は1ページ目で分割+3回の埋め込みを行うのでこの区間が長い。
    renderModal(
      {
        units: { page: unitStatus({ building: true }), tile: unitStatus() },
      },
      { progressFor: () => null },
    );
    const row = screen.getByRole('group', { name: 'ページ索引' });
    expect(within(row).getByText('準備中…')).toBeTruthy();
  });

  it('progress が来たら件数表示に切り替わる', () => {
    renderModal(
      {
        units: { page: unitStatus({ building: true }), tile: unitStatus() },
      },
      {
        progressFor: (u: string) =>
          u === 'page' ? { done: 3, total: 10, etaSeconds: null } : null,
      },
    );
    const row = screen.getByRole('group', { name: 'ページ索引' });
    expect(within(row).getByText(/3 \/ 10/)).toBeTruthy();
    expect(within(row).queryByText('準備中…')).toBeNull();
  });

  it('構築していない行には構築中表示を出さない', () => {
    renderModal({ units: { page: unitStatus(), tile: unitStatus() } });
    expect(screen.queryByText('準備中…')).toBeNull();
  });
});

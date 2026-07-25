import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import VisualIndexModal from '$lib/components/VisualIndexModal.svelte';

afterEach(() => cleanup());

function makeStatus(overrides: Record<string, unknown> = {}) {
  return {
    built: false, embedding_model: null, built_at: null,
    indexed_sources: 0, pending_sources: 0, building: false,
    extra_available: true, ...overrides,
  };
}

describe('VisualIndexModal', () => {
  it('未構築時は構築ボタンが有効、削除ボタンは出ない', async () => {
    render(VisualIndexModal, {
      notebookId: 'nb1', status: makeStatus(), onBuild: vi.fn(), onDelete: vi.fn(), onClose: vi.fn(),
    });
    const build = screen.getByRole('button', { name: '視覚インデックスを構築' });
    expect((build as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByRole('button', { name: '視覚インデックスを削除' })).toBeNull();
  });

  it('extra未導入時は構築ボタン無効+導入ヒント表示', () => {
    render(VisualIndexModal, {
      notebookId: 'nb1', status: makeStatus({ extra_available: false }),
      onBuild: vi.fn(), onDelete: vi.fn(), onClose: vi.fn(),
    });
    expect((screen.getByRole('button', { name: '視覚インデックスを構築' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/uv sync --extra visual/)).toBeTruthy();
  });

  it('構築済み時は状態と削除ボタンを表示、クリックでonDelete発火', async () => {
    const onDelete = vi.fn();
    render(VisualIndexModal, {
      notebookId: 'nb1',
      status: makeStatus({ built: true, embedding_model: 'vm', built_at: '2026-07-25T00:00:00Z', indexed_sources: 3, pending_sources: 1 }),
      onBuild: vi.fn(), onDelete, onClose: vi.fn(),
    });
    expect(screen.getByText(/vm/)).toBeTruthy();
    expect(screen.getByText(/未索引 1 件/)).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: '視覚インデックスを削除' }));
    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it('building中は構築ボタン無効+進捗表示', () => {
    render(VisualIndexModal, {
      notebookId: 'nb1', status: makeStatus({ building: true }),
      progress: { done: 3, total: 10 },
      onBuild: vi.fn(), onDelete: vi.fn(), onClose: vi.fn(),
    });
    expect((screen.getByRole('button', { name: '視覚インデックスを構築' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/3 \/ 10/)).toBeTruthy();
  });
});

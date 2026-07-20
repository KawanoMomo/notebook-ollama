/**
 * ParentPickerModal — 「親ソースを設定」で開く候補選択モーダル。
 * 仕様: docs/specs/2026-07-06-presentation-mode-design.md, Task 10 brief。
 *
 * 候補(自身と自身の子孫を除く同一NB内ソース)をボタンリストで表示し、
 * クリックで onPick(id) を呼ぶ。候補が0件なら案内メッセージを表示する。
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import ParentPickerModal from '$lib/components/ParentPickerModal.svelte';
import type { Source } from '$lib/api/types';

afterEach(() => cleanup());

function makeSource(id: string, overrides: Partial<Source> = {}): Source {
  return {
    id,
    notebook_id: 'nb1',
    kind: 'pdf',
    title: `資料${id}`,
    origin: null,
    status: 'ready',
    error_msg: null,
    bytes: null,
    page_count: null,
    chunk_count: 1,
    created_at: 't',
    updated_at: 't',
    ...overrides,
  };
}

describe('ParentPickerModal', () => {
  it('候補を表示し、クリックで onPick(id) を呼ぶ', async () => {
    const onPick = vi.fn();
    const onClose = vi.fn();
    render(ParentPickerModal, {
      props: { candidates: [makeSource('a'), makeSource('b')], onPick, onClose },
    });
    expect(screen.getByText('資料a')).toBeTruthy();
    expect(screen.getByText('資料b')).toBeTruthy();
    await fireEvent.click(screen.getByText('資料b'));
    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick).toHaveBeenCalledWith('b');
  });

  it('候補が0件のとき「リンク可能なソースがありません」を表示する', () => {
    render(ParentPickerModal, {
      props: { candidates: [], onPick: vi.fn(), onClose: vi.fn() },
    });
    expect(screen.getByText('リンク可能なソースがありません')).toBeTruthy();
  });
});

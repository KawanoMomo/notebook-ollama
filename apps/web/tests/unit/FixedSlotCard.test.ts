import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import FixedSlotCard from '$lib/components/settings/FixedSlotCard.svelte';
import type { FixedPromptSlotOut } from '$lib/api/types';

afterEach(() => cleanup());

function makeSlot(over: Partial<FixedPromptSlotOut> = {}): FixedPromptSlotOut {
  return {
    title: '',
    body: '',
    icon_url: null,
    ...over,
  };
}

function baseProps(slot: FixedPromptSlotOut, extra: Record<string, unknown> = {}) {
  return {
    slot,
    slotIndex: 0 as 0 | 1 | 2,
    onSave: vi.fn().mockResolvedValue(undefined),
    onClear: vi.fn().mockResolvedValue(undefined),
    onUploadIcon: vi.fn().mockResolvedValue(undefined),
    onDeleteIcon: vi.fn().mockResolvedValue(undefined),
    ...extra,
  };
}

describe('FixedSlotCard', () => {
  it('renders the initial title and body in inputs', () => {
    const slot = makeSlot({ title: '要約', body: '3 行で要約' });
    render(FixedSlotCard, baseProps(slot));
    expect(
      (screen.getByLabelText(/タイトル/) as HTMLInputElement).value,
    ).toBe('要約');
    expect(
      (screen.getByLabelText(/プロンプト本文/) as HTMLTextAreaElement).value,
    ).toBe('3 行で要約');
  });

  it('clicking 保存 calls onSave with the current draft values', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(FixedSlotCard, baseProps(makeSlot(), { onSave }));
    const titleInput = screen.getByLabelText(/タイトル/) as HTMLInputElement;
    const bodyInput = screen.getByLabelText(/プロンプト本文/) as HTMLTextAreaElement;
    await fireEvent.input(titleInput, { target: { value: '翻訳' } });
    await fireEvent.input(bodyInput, { target: { value: '英語に' } });
    await fireEvent.click(screen.getByRole('button', { name: /^保存$/ }));
    expect(onSave).toHaveBeenCalledWith('翻訳', '英語に');
  });

  it('clicking スロットを空に calls onClear', async () => {
    const onClear = vi.fn().mockResolvedValue(undefined);
    const slot = makeSlot({ title: 'X', body: 'Y' });
    render(FixedSlotCard, baseProps(slot, { onClear }));
    await fireEvent.click(screen.getByRole('button', { name: /空に/ }));
    expect(onClear).toHaveBeenCalled();
  });

  it('shows the icon preview when icon_url is provided', () => {
    const slot = makeSlot({
      title: '要約',
      body: 'X',
      icon_url: '/api/prompts/icons/x.png',
    });
    const { container } = render(FixedSlotCard, baseProps(slot));
    const img = container.querySelector('.preview img') as HTMLImageElement;
    expect(img).not.toBeNull();
    expect(img.src).toContain('/api/prompts/icons/x.png');
  });

  it('shows the title head character when no icon_url', () => {
    const slot = makeSlot({ title: '要約', body: 'X', icon_url: null });
    render(FixedSlotCard, baseProps(slot));
    // プレビュー領域に「要」が出る
    expect(screen.getAllByText('要').length).toBeGreaterThan(0);
  });

  it('clicking 画像を削除 calls onDeleteIcon (visible only when icon present)', async () => {
    const onDeleteIcon = vi.fn().mockResolvedValue(undefined);
    const slot = makeSlot({
      title: 'A',
      body: 'B',
      icon_url: '/api/prompts/icons/x.png',
    });
    render(FixedSlotCard, baseProps(slot, { onDeleteIcon }));
    await fireEvent.click(screen.getByRole('button', { name: /画像を削除/ }));
    expect(onDeleteIcon).toHaveBeenCalled();
  });

  it('does not show 画像を削除 when icon is absent', () => {
    render(FixedSlotCard, baseProps(makeSlot()));
    expect(
      screen.queryByRole('button', { name: /画像を削除/ }),
    ).toBeNull();
  });
});

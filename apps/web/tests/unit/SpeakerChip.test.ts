import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import SpeakerChip from '$lib/components/SpeakerChip.svelte';

afterEach(() => cleanup());

describe('SpeakerChip', () => {
  it('renders a plain (non-editable) chip when onRename is not provided', () => {
    render(SpeakerChip, { speaker: '相手1' });
    // 表示専用: 編集トリガ(ボタン)が存在しない
    expect(screen.queryByLabelText('話者名を編集')).toBeNull();
    expect(screen.getByText(/相手1/)).toBeTruthy();
    // span であって button ではない
    expect(screen.getByText(/相手1/).tagName).toBe('SPAN');
  });

  it('shows an editable chip button when onRename is provided', () => {
    render(SpeakerChip, { speaker: '相手1', onRename: vi.fn() });
    const trigger = screen.getByLabelText('話者名を編集');
    expect(trigger.tagName).toBe('BUTTON');
  });

  it('prefills the input with the current label and commits on Enter', async () => {
    const onRename = vi.fn();
    render(SpeakerChip, { speaker: '相手1', onRename });

    await fireEvent.click(screen.getByLabelText('話者名を編集'));
    const input = screen.getByLabelText<HTMLInputElement>('話者名を編集');
    expect(input.value).toBe('相手1'); // 現在ラベルでプリフィル
    await fireEvent.input(input, { target: { value: '田中さん' } });
    await fireEvent.keyDown(input, { key: 'Enter' });

    expect(onRename).toHaveBeenCalledTimes(1);
    expect(onRename).toHaveBeenCalledWith('相手1', '田中さん');
  });

  it('commits via the ✓ button', async () => {
    const onRename = vi.fn();
    render(SpeakerChip, { speaker: '相手1', onRename });

    await fireEvent.click(screen.getByLabelText('話者名を編集'));
    const input = screen.getByLabelText<HTMLInputElement>('話者名を編集');
    await fireEvent.input(input, { target: { value: '田中さん' } });
    await fireEvent.click(screen.getByLabelText('確定'));

    expect(onRename).toHaveBeenCalledTimes(1);
    expect(onRename).toHaveBeenCalledWith('相手1', '田中さん');
  });

  it('cancels edit on Escape without calling onRename', async () => {
    const onRename = vi.fn();
    render(SpeakerChip, { speaker: '相手1', onRename });

    await fireEvent.click(screen.getByLabelText('話者名を編集'));
    const input = screen.getByLabelText<HTMLInputElement>('話者名を編集');
    await fireEvent.input(input, { target: { value: '田中さん' } });
    await fireEvent.keyDown(input, { key: 'Escape' });

    expect(onRename).not.toHaveBeenCalled();
    // 編集欄が閉じ、編集トリガ(チップボタン)に戻る
    expect(screen.getByLabelText('話者名を編集').tagName).toBe('BUTTON');
  });

  it('cancels edit via the ✕ button', async () => {
    const onRename = vi.fn();
    render(SpeakerChip, { speaker: '相手1', onRename });

    await fireEvent.click(screen.getByLabelText('話者名を編集'));
    const input = screen.getByLabelText<HTMLInputElement>('話者名を編集');
    await fireEvent.input(input, { target: { value: '田中さん' } });
    await fireEvent.click(screen.getByLabelText('取消'));

    expect(onRename).not.toHaveBeenCalled();
    expect(screen.getByLabelText('話者名を編集').tagName).toBe('BUTTON');
  });

  it('does not call onRename when the value is unchanged', async () => {
    const onRename = vi.fn();
    render(SpeakerChip, { speaker: '相手1', onRename });

    await fireEvent.click(screen.getByLabelText('話者名を編集'));
    const input = screen.getByLabelText<HTMLInputElement>('話者名を編集');
    await fireEvent.keyDown(input, { key: 'Enter' });

    expect(onRename).not.toHaveBeenCalled();
  });

  it('does not call onRename when the value is empty / whitespace-only', async () => {
    const onRename = vi.fn();
    render(SpeakerChip, { speaker: '相手1', onRename });

    await fireEvent.click(screen.getByLabelText('話者名を編集'));
    const input = screen.getByLabelText<HTMLInputElement>('話者名を編集');
    await fireEvent.input(input, { target: { value: '   ' } });
    await fireEvent.keyDown(input, { key: 'Enter' });

    expect(onRename).not.toHaveBeenCalled();
  });
});

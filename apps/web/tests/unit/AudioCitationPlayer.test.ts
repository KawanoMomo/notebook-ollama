import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import AudioCitationPlayer from '$lib/components/AudioCitationPlayer.svelte';

const baseProps = {
  notebookId: 'nb1',
  sourceId: 'src1',
  startMs: 1000,
  endMs: 2000,
};

afterEach(() => cleanup());

describe('AudioCitationPlayer speaker chip inline edit', () => {
  it('shows a plain (non-editable) chip when onRenameSpeaker is not provided', () => {
    render(AudioCitationPlayer, { ...baseProps, speaker: '相手1' });
    // 表示専用: ボタン化されていない (編集トリガが存在しない)
    expect(screen.queryByLabelText('話者名を編集')).toBeNull();
    expect(screen.getByText(/相手1/)).toBeTruthy();
  });

  it('commits a new speaker name via onRenameSpeaker on Enter', async () => {
    const onRenameSpeaker = vi.fn();
    render(AudioCitationPlayer, { ...baseProps, speaker: '相手1', onRenameSpeaker });

    await fireEvent.click(screen.getByLabelText('話者名を編集'));
    const input = screen.getByLabelText<HTMLInputElement>('話者名を編集');
    expect(input.value).toBe('相手1'); // 現在ラベルでプリフィル
    await fireEvent.input(input, { target: { value: '田中さん' } });
    await fireEvent.keyDown(input, { key: 'Enter' });

    expect(onRenameSpeaker).toHaveBeenCalledTimes(1);
    expect(onRenameSpeaker).toHaveBeenCalledWith('相手1', '田中さん');
  });

  it('cancels edit on Escape without calling onRenameSpeaker', async () => {
    const onRenameSpeaker = vi.fn();
    render(AudioCitationPlayer, { ...baseProps, speaker: '相手1', onRenameSpeaker });

    await fireEvent.click(screen.getByLabelText('話者名を編集'));
    const input = screen.getByLabelText<HTMLInputElement>('話者名を編集');
    await fireEvent.input(input, { target: { value: '田中さん' } });
    await fireEvent.keyDown(input, { key: 'Escape' });

    expect(onRenameSpeaker).not.toHaveBeenCalled();
    // 編集欄が閉じ、編集トリガ(チップボタン)に戻る
    expect(screen.getByLabelText('話者名を編集').tagName).toBe('BUTTON');
  });

  it('does not call onRenameSpeaker when the value is unchanged', async () => {
    const onRenameSpeaker = vi.fn();
    render(AudioCitationPlayer, { ...baseProps, speaker: '相手1', onRenameSpeaker });

    await fireEvent.click(screen.getByLabelText('話者名を編集'));
    const input = screen.getByLabelText<HTMLInputElement>('話者名を編集');
    await fireEvent.keyDown(input, { key: 'Enter' });

    expect(onRenameSpeaker).not.toHaveBeenCalled();
  });

  it('does not call onRenameSpeaker when the value is empty', async () => {
    const onRenameSpeaker = vi.fn();
    render(AudioCitationPlayer, { ...baseProps, speaker: '相手1', onRenameSpeaker });

    await fireEvent.click(screen.getByLabelText('話者名を編集'));
    const input = screen.getByLabelText<HTMLInputElement>('話者名を編集');
    await fireEvent.input(input, { target: { value: '   ' } });
    await fireEvent.keyDown(input, { key: 'Enter' });

    expect(onRenameSpeaker).not.toHaveBeenCalled();
  });
});

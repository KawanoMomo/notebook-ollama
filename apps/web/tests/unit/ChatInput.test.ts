import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import ChatInput from '$lib/components/ChatInput.svelte';

afterEach(() => cleanup());

describe('ChatInput — 0件選択ブロック', () => {
  it('shows orange warning bar when sourcesSelected=0', () => {
    render(ChatInput, {
      streaming: false,
      hint: null,
      sourcesSelected: 0,
      onSend: vi.fn(),
      onCancel: vi.fn(),
    });
    const bar = screen.getByRole('alert');
    expect(bar.textContent).toMatch(/ソースが選択されていません/);
  });

  it('hides the warning bar when sourcesSelected>=1', () => {
    render(ChatInput, {
      streaming: false,
      hint: null,
      sourcesSelected: 1,
      onSend: vi.fn(),
      onCancel: vi.fn(),
    });
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('disables send when sourcesSelected=0 and does not call onSend', async () => {
    const onSend = vi.fn();
    render(ChatInput, {
      streaming: false,
      hint: null,
      sourcesSelected: 0,
      onSend,
      onCancel: vi.fn(),
    });
    const ta = screen.getByPlaceholderText(/質問を入力/);
    await fireEvent.input(ta, { target: { value: 'hello' } });
    const btn = screen.getByRole('button', { name: /送信/ });
    expect((btn as HTMLButtonElement).disabled).toBe(true);
    await fireEvent.click(btn);
    expect(onSend).not.toHaveBeenCalled();
  });

  it('enables send when sourcesSelected>=1 and forwards the text', async () => {
    const onSend = vi.fn();
    render(ChatInput, {
      streaming: false,
      hint: null,
      sourcesSelected: 2,
      onSend,
      onCancel: vi.fn(),
    });
    const ta = screen.getByPlaceholderText(/質問を入力/);
    await fireEvent.input(ta, { target: { value: 'hello' } });
    const btn = screen.getByRole('button', { name: /送信/ });
    expect((btn as HTMLButtonElement).disabled).toBe(false);
    await fireEvent.click(btn);
    expect(onSend).toHaveBeenCalledWith('hello');
  });
});

import '@testing-library/jest-dom/vitest';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/svelte';
import VoiceInputSection from '$lib/components/settings/VoiceInputSection.svelte';

const putVoiceInput = vi.fn(async (body: unknown) => body);
vi.mock('$lib/api/settings', () => ({
  settingsApi: {
    get putVoiceInput() { return putVoiceInput; },
  },
}));

// settings 全体を null にできる形にする(ロード前ゲートのテスト用)。
const state: {
  settings: { voice_input: { mode: string; ptt_key: string } | null } | null;
} = {
  settings: { voice_input: { mode: 'push_to_talk', ptt_key: 'Space' } },
};
vi.mock('$lib/stores/settings.svelte', () => ({
  settingsStore: {
    get settings() { return state.settings; },
    load: vi.fn(async () => {}),
  },
}));

beforeEach(() => {
  putVoiceInput.mockClear();
  state.settings = { voice_input: { mode: 'push_to_talk', ptt_key: 'Space' } };
});

describe('VoiceInputSection', () => {
  it('モード 3 値のラジオと現在キーを表示する', () => {
    render(VoiceInputSection);
    expect(screen.getByRole('radio', { name: /無効/ })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /プッシュトゥトーク/ })).toBeChecked();
    expect(screen.getByRole('radio', { name: /常時有効/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Space/ })).toBeInTheDocument();
  });

  it('保存でモードとキーが PUT される', async () => {
    render(VoiceInputSection);
    await fireEvent.click(screen.getByRole('radio', { name: /常時有効/ }));
    await fireEvent.click(screen.getByRole('button', { name: '保存' }));
    expect(putVoiceInput).toHaveBeenCalledWith({ mode: 'hands_free', ptt_key: 'Space' });
  });

  it('キー割当: ボタン押下 → キー入力で code を採用', async () => {
    render(VoiceInputSection);
    const keyBtn = screen.getByRole('button', { name: /Space/ });
    await fireEvent.click(keyBtn); // キャプチャモードへ
    await fireEvent.keyDown(window, { code: 'KeyV' });
    expect(screen.getByRole('button', { name: /KeyV/ })).toBeInTheDocument();
  });

  it('キー割当: Esc でキャンセルし元のキーを保持', async () => {
    render(VoiceInputSection);
    await fireEvent.click(screen.getByRole('button', { name: /Space/ }));
    await fireEvent.keyDown(window, { code: 'Escape' });
    expect(screen.getByRole('button', { name: /Space/ })).toBeInTheDocument();
  });

  it('モードが PTT 以外のときキー割当は disabled', async () => {
    render(VoiceInputSection);
    await fireEvent.click(screen.getByRole('radio', { name: /無効/ }));
    expect(screen.getByRole('button', { name: /Space/ })).toBeDisabled();
  });

  it('設定ロード前は読み込み中表示で編集UIを出さない', () => {
    state.settings = null;
    render(VoiceInputSection);
    expect(screen.queryByRole('radio')).toBeNull();
    expect(screen.getByText(/読み込み中/)).toBeInTheDocument();
  });
});

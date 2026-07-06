import '@testing-library/jest-dom/vitest';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import ChatInput from '$lib/components/ChatInput.svelte';

// settingsStore: voice_input モードを制御できる薄い fake
// (vi.mock ファクトリは import より先にホイストされるため、参照する可変状態は
//  vi.hoisted で包んで TDZ エラー「Cannot access before initialization」を回避する)
const { settingsState } = vi.hoisted(() => ({
  settingsState: {
    voice_input: { mode: 'push_to_talk', ptt_key: 'Space' } as
      | { mode: string; ptt_key: string }
      | null,
  },
}));
vi.mock('$lib/stores/settings.svelte', () => ({
  settingsStore: {
    get settings() {
      return { voice_input: settingsState.voice_input };
    },
    load: vi.fn(async () => {}),
  },
}));

// voiceInputStore: 状態を直接切り替えられる fake
const { voiceState, voiceMock } = vi.hoisted(() => {
  const state = { status: 'idle' };
  const mock = {
    get status() { return state.status; },
    elapsedSec: 0,
    setCallbacks: vi.fn(),
    pttPressStart: vi.fn(),
    pttTapCancel: vi.fn(),
    pttHoldStart: vi.fn(),
    pttHoldEnd: vi.fn(async () => {}),
    handsFreeToggle: vi.fn(async () => {}),
    stopAll: vi.fn(),
  };
  return { voiceState: state, voiceMock: mock };
});
vi.mock('$lib/stores/voiceInput.svelte', () => ({
  voiceInputStore: voiceMock,
  PTT_MAX_MS: 120_000,
}));

// promptsStore は既存 onMount で load される — 空で満たす
// (PromptToolbar は prompts: null を「未ロード」として degraded 描画するため
//  [] ではなく null を渡す — [] は truthy で prompts.fixed アクセスがクラッシュする)
vi.mock('$lib/stores/prompts.svelte', () => ({
  promptsStore: { prompts: null, load: vi.fn(async () => {}) },
}));

const baseProps = {
  streaming: false,
  sourcesSelected: 1,
  onSend: vi.fn(),
  onCancel: vi.fn(),
};

beforeEach(() => {
  voiceState.status = 'idle';
  settingsState.voice_input = { mode: 'push_to_talk', ptt_key: 'Space' };
});

describe('ChatInput 音声入力', () => {
  it('mode=push_to_talk でマイクボタンが表示される', () => {
    render(ChatInput, { props: baseProps });
    expect(screen.getByRole('button', { name: '音声入力' })).toBeInTheDocument();
  });

  it('mode=off ではマイクボタンを表示しない', () => {
    settingsState.voice_input = { mode: 'off', ptt_key: 'Space' };
    render(ChatInput, { props: baseProps });
    expect(screen.queryByRole('button', { name: '音声入力' })).toBeNull();
  });

  it('録音中は aria-pressed と経過表示になる', () => {
    voiceState.status = 'recording';
    render(ChatInput, { props: baseProps });
    const btn = screen.getByRole('button', { name: '音声入力' });
    expect(btn).toHaveAttribute('aria-pressed', 'true');
  });

  it('mode=hands_free のクリックで handsFreeToggle が呼ばれる', async () => {
    settingsState.voice_input = { mode: 'hands_free', ptt_key: 'Space' };
    render(ChatInput, { props: baseProps });
    screen.getByRole('button', { name: '音声入力' }).click();
    expect(voiceMock.handsFreeToggle).toHaveBeenCalled();
  });

  describe('PTT キーフックの対象範囲・キャプチャ開始タイミング(Fix 1 / Fix 2)', () => {
    beforeEach(() => {
      // 前のテストで蓄積した呼び出し履歴(pttPressStart 等)を持ち越さない
      vi.clearAllMocks();
    });
    afterEach(() => {
      vi.useRealTimers();
      document.body.querySelectorAll('[data-test-foreign-btn]').forEach((el) => el.remove());
    });

    it('インタラクティブ要素フォーカス中はSpaceを奪わない', () => {
      render(ChatInput, { props: baseProps });
      const foreignButton = document.createElement('button');
      foreignButton.setAttribute('data-test-foreign-btn', '');
      document.body.appendChild(foreignButton);
      foreignButton.focus();

      const keydown = new KeyboardEvent('keydown', {
        code: 'Space',
        bubbles: true,
        cancelable: true,
      });
      foreignButton.dispatchEvent(keydown);

      expect(keydown.defaultPrevented).toBe(false);
      expect(voiceMock.pttPressStart).not.toHaveBeenCalled();
      expect(voiceMock.pttHoldStart).not.toHaveBeenCalled();
    });

    it('長押し確定までキャプチャを開始しない', () => {
      vi.useFakeTimers();
      render(ChatInput, { props: baseProps });
      const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
      textarea.focus();

      const keydown = new KeyboardEvent('keydown', {
        code: 'Space',
        bubbles: true,
        cancelable: true,
      });
      textarea.dispatchEvent(keydown);
      expect(voiceMock.pttPressStart).not.toHaveBeenCalled();

      vi.advanceTimersByTime(250);
      expect(voiceMock.pttPressStart).toHaveBeenCalledTimes(1);
      expect(voiceMock.pttHoldStart).toHaveBeenCalledTimes(1);

      const keyup = new KeyboardEvent('keyup', {
        code: 'Space',
        bubbles: true,
        cancelable: true,
      });
      textarea.dispatchEvent(keyup);
      expect(voiceMock.pttHoldEnd).toHaveBeenCalledTimes(1);
    });

    it('タップではストアを一切呼ばない', () => {
      vi.useFakeTimers();
      render(ChatInput, { props: baseProps });
      const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
      textarea.focus();

      const keydown = new KeyboardEvent('keydown', {
        code: 'Space',
        bubbles: true,
        cancelable: true,
      });
      textarea.dispatchEvent(keydown);
      vi.advanceTimersByTime(100);

      const keyup = new KeyboardEvent('keyup', {
        code: 'Space',
        bubbles: true,
        cancelable: true,
      });
      textarea.dispatchEvent(keyup);

      expect(voiceMock.pttPressStart).not.toHaveBeenCalled();
      expect(voiceMock.pttTapCancel).not.toHaveBeenCalled();
      expect(keydown.defaultPrevented).toBe(true);
    });
  });
});

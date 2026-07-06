import '@testing-library/jest-dom/vitest';
import { beforeEach, describe, expect, it, vi } from 'vitest';
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
});

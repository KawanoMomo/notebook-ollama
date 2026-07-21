import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';

const storeState: Record<string, unknown> = {};
vi.mock('$lib/stores/conversation.svelte', () => ({
  get conversationStore() {
    return storeState.store;
  },
}));

vi.mock('$lib/stores/currentNotebook.svelte', () => ({
  currentNotebookStore: { selectedSourceIds: new Set(['s1']) },
}));

import MessageList from '$lib/components/MessageList.svelte';

function makeStore(overrides: Record<string, unknown> = {}) {
  return {
    messages: [], streaming: false, streamingText: '', streamingHits: [],
    thinkingChars: 0, continuingInfo: null, error: null, warning: null,
    continueLast: vi.fn(),
    ...overrides,
  };
}

const truncatedMsg = {
  id: 'm1', conversation_id: 'c1', role: 'assistant',
  content: '途中まで', citations: [], model: 'm', created_at: '',
  truncated: true,
};

afterEach(() => cleanup());

describe('MessageList — 続きを生成', () => {
  it('最後の truncated メッセージにボタンが出てクリックで continueLast', async () => {
    const store = makeStore({ messages: [truncatedMsg] });
    storeState.store = store;
    render(MessageList, { onCitationClick: vi.fn() });
    const btn = screen.getByRole('button', { name: /続きを生成/ });
    await fireEvent.click(btn);
    expect(store.continueLast).toHaveBeenCalledWith(['s1']);
  });

  it('streaming 中はボタンを出さない', () => {
    storeState.store = makeStore({ messages: [truncatedMsg], streaming: true });
    render(MessageList, { onCitationClick: vi.fn() });
    expect(screen.queryByRole('button', { name: /続きを生成/ })).toBeNull();
  });

  it('continuingInfo 表示中は「続きを生成中… (1/2)」が出る', () => {
    storeState.store = makeStore({
      streaming: true, streamingText: '本文', continuingInfo: { round: 1, max: 2 },
    });
    render(MessageList, { onCitationClick: vi.fn() });
    expect(screen.getByText(/続きを生成中… \(1\/2\)/)).toBeTruthy();
  });
});

/**
 * promptsStore のユニットテスト。設計: docs/specs/2026-06-26-prompt-injection-design.md
 *
 * 純粋関数 (movePromptIds) とストアの並び替え/CRUD 動作を検証する。
 */
import { describe, expect, it, vi } from 'vitest';
import { createPromptsStore, movePromptIds } from '$lib/stores/prompts.svelte';
import type { PromptsOut } from '$lib/api/types';

function emptyPrompts(): PromptsOut {
  return {
    fixed: [
      { title: '', body: '', icon_url: null },
      { title: '', body: '', icon_url: null },
      { title: '', body: '', icon_url: null },
    ],
    dropdown: [],
  };
}

describe('movePromptIds — 純粋関数', () => {
  const ids = ['a', 'b', 'c', 'd'];

  it('moves an id up by 1 (delta=-1)', () => {
    expect(movePromptIds(ids, 'c', -1)).toEqual(['a', 'c', 'b', 'd']);
  });

  it('moves an id down by 1 (delta=+1)', () => {
    expect(movePromptIds(ids, 'b', 1)).toEqual(['a', 'c', 'b', 'd']);
  });

  it('does not move the first id up further', () => {
    expect(movePromptIds(ids, 'a', -1)).toEqual(ids);
  });

  it('does not move the last id down further', () => {
    expect(movePromptIds(ids, 'd', 1)).toEqual(ids);
  });

  it('returns the same array when id is unknown', () => {
    expect(movePromptIds(ids, 'ghost', -1)).toEqual(ids);
  });
});

describe('promptsStore', () => {
  it('starts with null prompts before load()', () => {
    const fakeApi = {
      get: vi.fn().mockResolvedValue(emptyPrompts()),
    } as any;
    const store = createPromptsStore(fakeApi);
    expect(store.prompts).toBeNull();
    expect(store.loading).toBe(false);
    expect(store.error).toBeNull();
  });

  it('load() populates prompts', async () => {
    const fakeApi = {
      get: vi.fn().mockResolvedValue(emptyPrompts()),
    } as any;
    const store = createPromptsStore(fakeApi);
    await store.load();
    expect(store.prompts).toEqual(emptyPrompts());
  });

  it('load() sets error and keeps prompts null on failure', async () => {
    const fakeApi = {
      get: vi.fn().mockRejectedValue(new Error('boom')),
    } as any;
    const store = createPromptsStore(fakeApi);
    await store.load();
    expect(store.prompts).toBeNull();
    expect(store.error).toBe('boom');
  });

  it('saveFixed() merges API response into prompts', async () => {
    const initial = emptyPrompts();
    const after: PromptsOut = {
      ...initial,
      fixed: [
        { title: '要約', body: '3行で要約', icon_url: null },
        initial.fixed[1],
        initial.fixed[2],
      ],
    };
    const fakeApi = {
      get: vi.fn().mockResolvedValue(initial),
      putFixed: vi.fn().mockResolvedValue(after),
    } as any;
    const store = createPromptsStore(fakeApi);
    await store.load();
    await store.saveFixed(0, '要約', '3行で要約');
    expect(fakeApi.putFixed).toHaveBeenCalledWith(0, '要約', '3行で要約');
    expect(store.prompts?.fixed[0].title).toBe('要約');
  });

  it('moveDropdown() reorders by delta and calls reorderDropdown', async () => {
    const p: PromptsOut = {
      fixed: emptyPrompts().fixed,
      dropdown: [
        { id: 'a', title: 'A', body: 'a' },
        { id: 'b', title: 'B', body: 'b' },
        { id: 'c', title: 'C', body: 'c' },
      ],
    };
    const reordered: PromptsOut = {
      fixed: p.fixed,
      dropdown: [p.dropdown[1], p.dropdown[0], p.dropdown[2]],
    };
    const fakeApi = {
      get: vi.fn().mockResolvedValue(p),
      reorderDropdown: vi.fn().mockResolvedValue(reordered),
    } as any;
    const store = createPromptsStore(fakeApi);
    await store.load();
    await store.moveDropdown('a', 1); // a を一つ下に
    expect(fakeApi.reorderDropdown).toHaveBeenCalledWith(['b', 'a', 'c']);
    expect(store.prompts?.dropdown[0].id).toBe('b');
  });
});

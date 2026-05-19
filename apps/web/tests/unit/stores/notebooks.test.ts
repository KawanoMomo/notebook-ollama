import { describe, expect, it, vi } from 'vitest';
import { createNotebooksStore } from '$lib/stores/notebooks.svelte';
import type { Notebook } from '$lib/api/types';

const makeNb = (overrides: Partial<Notebook> = {}): Notebook => ({
  id: '01HF' + 'A'.repeat(22),
  name: 'N',
  description: null,
  default_model: null,
  created_at: '',
  updated_at: '',
  source_count: 0,
  ...overrides,
});

describe('notebooks store', () => {
  it('loads notebooks via api', async () => {
    const api = { list: vi.fn().mockResolvedValue([makeNb({ id: 'a' }), makeNb({ id: 'b' })]) };
    const store = createNotebooksStore(api as never);
    await store.load();
    expect(store.items.length).toBe(2);
  });

  it('add prepends a notebook', () => {
    const api = { list: vi.fn() };
    const store = createNotebooksStore(api as never);
    store.add(makeNb({ id: 'x' }));
    expect(store.items[0].id).toBe('x');
  });

  it('remove deletes a notebook', () => {
    const api = { list: vi.fn() };
    const store = createNotebooksStore(api as never);
    store.add(makeNb({ id: 'a' }));
    store.add(makeNb({ id: 'b' }));
    store.remove('a');
    expect(store.items.map((n) => n.id)).toEqual(['b']);
  });

  it('captures load error', async () => {
    const api = { list: vi.fn().mockRejectedValue(new Error('boom')) };
    const store = createNotebooksStore(api as never);
    await store.load();
    expect(store.error).toBe('boom');
  });
});

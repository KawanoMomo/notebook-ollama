import { describe, expect, it } from 'vitest';
import { createNavMemoryStore } from '$lib/stores/navMemory.svelte';

describe('navMemory store', () => {
  it('defaults lastPath to "/"', () => {
    const store = createNavMemoryStore();
    expect(store.lastPath).toBe('/');
  });

  it('records a non-settings path', () => {
    const store = createNavMemoryStore();
    store.record('/notebooks/abc');
    expect(store.lastPath).toBe('/notebooks/abc');
  });

  it('ignores settings paths (keeps previous)', () => {
    const store = createNavMemoryStore();
    store.record('/notebooks/abc');
    store.record('/settings');
    expect(store.lastPath).toBe('/notebooks/abc');
  });

  it('keeps default when only settings visited', () => {
    const store = createNavMemoryStore();
    store.record('/settings');
    expect(store.lastPath).toBe('/');
  });
});

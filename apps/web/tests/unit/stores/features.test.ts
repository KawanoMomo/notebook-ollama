import { describe, expect, it, vi } from 'vitest';
import { createFeaturesStore } from '$lib/stores/features.svelte';
import type { FeatureFlagInfo } from '$lib/api/types';

function makeFlag(overrides: Partial<FeatureFlagInfo> = {}): FeatureFlagInfo {
  return {
    id: 'table-figure-rag',
    name: '表・図検索強化',
    description: 'PDFの表・図を抽出し、検索と回答に反映するベータ機能',
    stage: 'beta',
    enabled: false,
    ...overrides,
  };
}

function makeApi(features: FeatureFlagInfo[] = []) {
  return {
    list: vi.fn().mockResolvedValue({ features }),
    setOptin: vi.fn().mockResolvedValue({ features }),
  };
}

describe('features store', () => {
  it('starts empty (flags=[], betaFlags=[])', () => {
    const store = createFeaturesStore(makeApi() as never);
    expect(store.flags).toEqual([]);
    expect(store.betaFlags).toEqual([]);
    expect(store.loading).toBe(false);
    expect(store.error).toBeNull();
  });

  it('load() populates flags and betaFlags from the API', async () => {
    const flags = [makeFlag({ id: 'a' }), makeFlag({ id: 'b' })];
    const api = makeApi(flags);
    const store = createFeaturesStore(api as never);

    await store.load();

    expect(api.list).toHaveBeenCalledTimes(1);
    expect(store.flags).toEqual(flags);
    expect(store.betaFlags).toEqual(flags);
    expect(store.loading).toBe(false);
    expect(store.error).toBeNull();
  });

  it('betaFlags excludes stage=ga flags', async () => {
    const flags = [
      makeFlag({ id: 'beta-1', stage: 'beta' }),
      makeFlag({ id: 'ga-1', stage: 'ga', enabled: true }),
    ];
    const store = createFeaturesStore(makeApi(flags) as never);
    await store.load();
    expect(store.flags).toHaveLength(2);
    expect(store.betaFlags.map((f) => f.id)).toEqual(['beta-1']);
  });

  it('load() with empty backend response yields betaFlags=[]', async () => {
    const store = createFeaturesStore(makeApi([]) as never);
    await store.load();
    expect(store.flags).toEqual([]);
    expect(store.betaFlags).toEqual([]);
  });

  it('load() failure sets error and leaves flags empty', async () => {
    const api = {
      list: vi.fn().mockRejectedValue(new Error('network down')),
      setOptin: vi.fn(),
    };
    const store = createFeaturesStore(api as never);
    await store.load();
    expect(store.error).toBe('network down');
    expect(store.flags).toEqual([]);
    expect(store.loading).toBe(false);
  });

  it('setOptin(id, enabled) calls API and replaces flags with the response', async () => {
    const initial = [makeFlag({ id: 'a', enabled: false })];
    const api = makeApi(initial);
    const store = createFeaturesStore(api as never);
    await store.load();

    const updated = [makeFlag({ id: 'a', enabled: true })];
    api.setOptin.mockResolvedValueOnce({ features: updated });

    await store.setOptin('a', true);

    expect(api.setOptin).toHaveBeenCalledWith('a', true);
    expect(store.flags).toEqual(updated);
    expect(store.betaFlags[0].enabled).toBe(true);
  });

  it('setOptin(id, false) round trip', async () => {
    const initial = [makeFlag({ id: 'a', enabled: true })];
    const api = makeApi(initial);
    const store = createFeaturesStore(api as never);
    await store.load();

    api.setOptin.mockResolvedValueOnce({
      features: [makeFlag({ id: 'a', enabled: false })],
    });
    await store.setOptin('a', false);

    expect(api.setOptin).toHaveBeenCalledWith('a', false);
    expect(store.betaFlags[0].enabled).toBe(false);
  });

  it('setOptin failure propagates and flags are NOT mutated', async () => {
    const initial = [makeFlag({ id: 'a', enabled: false })];
    const api = {
      list: vi.fn().mockResolvedValue({ features: initial }),
      setOptin: vi.fn().mockRejectedValue(new Error('500')),
    };
    const store = createFeaturesStore(api as never);
    await store.load();

    await expect(store.setOptin('a', true)).rejects.toThrow('500');
    expect(store.flags).toEqual(initial);
    expect(store.betaFlags[0].enabled).toBe(false);
  });

  it('two stores from createFeaturesStore() are independent (no shared state)', async () => {
    const store1 = createFeaturesStore(makeApi([makeFlag({ id: 'a' })]) as never);
    const store2 = createFeaturesStore(
      makeApi([makeFlag({ id: 'x' }), makeFlag({ id: 'y' })]) as never,
    );

    await store1.load();
    await store2.load();

    expect(store1.flags).toHaveLength(1);
    expect(store2.flags).toHaveLength(2);
  });
});

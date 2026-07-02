import { describe, expect, it, vi } from 'vitest';
import { createCrashReportsStore } from '$lib/stores/crashReports.svelte';
import type { CrashHardware, CrashSource, PendingCrash } from '$lib/api/types';

const HARDWARE_PLACEHOLDER: CrashHardware = {
  cpu_model: 'cpu',
  cpu_cores: 8,
  cpu_threads: 16,
  ram_total_gb: 32,
  ram_available_gb: 16,
  gpu_model: 'RTX2080Ti',
  gpu_vram_mb: 11264,
  driver_version: '555.00',
  disk_free_gb: 500,
  os_platform: 'Windows-11',
  python_version: '3.12.5',
};

function makeCrash(overrides: Partial<PendingCrash> = {}): PendingCrash {
  return {
    id: 'crash-1',
    fingerprint: 'fp-1',
    created_at: '2026-06-28T00:00:00Z',
    exception_type: 'RuntimeError',
    exception_message: 'boom',
    trace: ['frame 1', 'frame 2'],
    hardware: HARDWARE_PLACEHOLDER,
    log_tail: [],
    source: 'fastapi',
    ...overrides,
  };
}

// spec §4.1 の全 CrashSource を網羅 (lessons learned: enum を手で間引かない)
const ALL_SOURCES: CrashSource[] = [
  'fastapi',
  'excepthook',
  'signal',
  'atexit',
  'frontend',
  'unclean_shutdown',
];

function makeApi(initial: PendingCrash[] = []) {
  return {
    listPending: vi.fn().mockResolvedValue(initial),
    dismiss: vi.fn().mockResolvedValue(undefined),
    markReported: vi.fn().mockResolvedValue(undefined),
  };
}

describe('crashReports store', () => {
  it('starts empty (pending=[], pendingCount=0)', () => {
    const store = createCrashReportsStore(makeApi() as never);
    expect(store.pending).toEqual([]);
    expect(store.pendingCount).toBe(0);
  });

  it('load() populates pending and updates pendingCount', async () => {
    const items = [makeCrash({ id: 'a' }), makeCrash({ id: 'b' }), makeCrash({ id: 'c' })];
    const api = makeApi(items);
    const store = createCrashReportsStore(api as never);

    await store.load();

    expect(api.listPending).toHaveBeenCalledTimes(1);
    expect(store.pending).toEqual(items);
    expect(store.pendingCount).toBe(3);
  });

  it('load() with empty backend response yields pendingCount=0', async () => {
    const store = createCrashReportsStore(makeApi([]) as never);
    await store.load();
    expect(store.pending).toEqual([]);
    expect(store.pendingCount).toBe(0);
  });

  // lessons learned: parametrize over the full enum
  it.each(ALL_SOURCES)('load() preserves source=%s round trip', async (source) => {
    const items = [makeCrash({ id: `c-${source}`, source })];
    const store = createCrashReportsStore(makeApi(items) as never);
    await store.load();
    expect(store.pending[0].source).toBe(source);
  });

  it('handles unicode (CJK + emoji) in exception_message and trace', async () => {
    const items = [
      makeCrash({
        id: 'cjk-1',
        exception_message: '致命的なエラーが発生しました 💥',
        trace: ['ファイル "app.py", 行 42, in メイン関数', '  raise RuntimeError("失敗")'],
      }),
    ];
    const store = createCrashReportsStore(makeApi(items) as never);
    await store.load();
    expect(store.pending[0].exception_message).toBe('致命的なエラーが発生しました 💥');
    expect(store.pending[0].trace[0]).toContain('メイン関数');
  });

  it('dismiss(id) calls API then removes the report from pending', async () => {
    const items = [makeCrash({ id: 'a' }), makeCrash({ id: 'b' }), makeCrash({ id: 'c' })];
    const api = makeApi(items);
    const store = createCrashReportsStore(api as never);
    await store.load();

    await store.dismiss('b');

    expect(api.dismiss).toHaveBeenCalledWith('b');
    expect(store.pending.map((p) => p.id)).toEqual(['a', 'c']);
    expect(store.pendingCount).toBe(2);
  });

  it('markReported(id) calls API then removes the report from pending', async () => {
    const items = [makeCrash({ id: 'a' }), makeCrash({ id: 'b' })];
    const api = makeApi(items);
    const store = createCrashReportsStore(api as never);
    await store.load();

    await store.markReported('a');

    expect(api.markReported).toHaveBeenCalledWith('a');
    expect(store.pending.map((p) => p.id)).toEqual(['b']);
    expect(store.pendingCount).toBe(1);
  });

  it('dismiss(id) for an unknown id still calls API but leaves pending unchanged', async () => {
    const items = [makeCrash({ id: 'a' })];
    const api = makeApi(items);
    const store = createCrashReportsStore(api as never);
    await store.load();

    await store.dismiss('does-not-exist');

    expect(api.dismiss).toHaveBeenCalledWith('does-not-exist');
    expect(store.pending.map((p) => p.id)).toEqual(['a']);
    expect(store.pendingCount).toBe(1);
  });

  it('dismiss(id) failure propagates and pending is NOT mutated', async () => {
    const items = [makeCrash({ id: 'a' }), makeCrash({ id: 'b' })];
    const api = {
      listPending: vi.fn().mockResolvedValue(items),
      dismiss: vi.fn().mockRejectedValue(new Error('network down')),
      markReported: vi.fn().mockResolvedValue(undefined),
    };
    const store = createCrashReportsStore(api as never);
    await store.load();

    await expect(store.dismiss('a')).rejects.toThrow('network down');
    expect(store.pending.map((p) => p.id)).toEqual(['a', 'b']);
    expect(store.pendingCount).toBe(2);
  });

  it('markReported(id) failure propagates and pending is NOT mutated', async () => {
    const items = [makeCrash({ id: 'a' })];
    const api = {
      listPending: vi.fn().mockResolvedValue(items),
      dismiss: vi.fn().mockResolvedValue(undefined),
      markReported: vi.fn().mockRejectedValue(new Error('500')),
    };
    const store = createCrashReportsStore(api as never);
    await store.load();

    await expect(store.markReported('a')).rejects.toThrow('500');
    expect(store.pending.map((p) => p.id)).toEqual(['a']);
    expect(store.pendingCount).toBe(1);
  });

  it('two stores from createCrashReportsStore() are independent (no shared state)', async () => {
    const api1 = makeApi([makeCrash({ id: 'a' })]);
    const api2 = makeApi([makeCrash({ id: 'x' }), makeCrash({ id: 'y' })]);
    const store1 = createCrashReportsStore(api1 as never);
    const store2 = createCrashReportsStore(api2 as never);

    await store1.load();
    await store2.load();

    expect(store1.pendingCount).toBe(1);
    expect(store2.pendingCount).toBe(2);

    await store1.dismiss('a');
    expect(store1.pendingCount).toBe(0);
    expect(store2.pendingCount).toBe(2); // 影響しない
  });
});

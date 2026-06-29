/**
 * errorBoundary → crashReportsStore.showImmediate handoff (Sprint 5 §5.6).
 *
 * REGRESSION: Playwright S4/S5 showed that `initErrorBoundary()` posts the
 * crash to `POST /api/crash/report` successfully (backend's
 * `/api/crash/pending` confirms the row) but `CrashDetectionModal` never
 * mounts. Root cause: `reportOnce()` discarded the resolved `PendingCrash`
 * returned by `crashApi.reportFrontendCrash(payload)` and never pushed it
 * into `crashReportsStore.activeImmediate`, which is the reactive field
 * `+layout.svelte` watches to mount the modal.
 *
 * This file pins the handoff so the pipeline cannot regress to
 * "API call succeeds, modal stays dark".
 *
 * Companion contract:
 *   - `crashApi.reportFrontendCrash` returns the persisted `PendingCrash`
 *     (matches backend `apps/api/routers/crash.py::PendingCrashOut`).
 *   - The store contract is `crashReports.svelte.ts::showImmediate(crash)`
 *     (latest-wins single slot; layout `#if activeImmediate` watches it).
 *   - `+layout.svelte` calls `initErrorBoundary()` on mount (`layout-wiring.test.ts`).
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '$lib/api/client';
import type { CrashReportInput } from '$lib/api/crash';
import type { CrashHardware, PendingCrash } from '$lib/api/types';

// Settings gate (Sprint 7): the showImmediate handoff is only exercised
// when the user is opted in AND `auto_prompt === true`. These tests pin the
// async handoff itself (PendingCrash → store.showImmediate), so we mock the
// singleton to that "both flags on" state. The gate's own truth table lives
// in `errorBoundary.gate.test.ts`.
vi.mock('$lib/stores/settings.svelte', () => ({
  settingsStore: {
    get crashReport() {
      return {
        enabled: true,
        auto_prompt: true,
        opted_in_at: '2026-06-29T00:00:00Z',
      };
    },
  },
}));

import { initErrorBoundary } from '$lib/utils/errorBoundary';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const HARDWARE: CrashHardware = {
  cpu_model: 'Intel i9-12900KF',
  cpu_cores: 16,
  cpu_threads: 24,
  ram_total_gb: 32,
  ram_available_gb: 18.5,
  gpu_model: 'NVIDIA RTX 2080 Ti',
  gpu_vram_mb: 11264,
  driver_version: '551.86',
  disk_free_gb: 512,
  os_platform: 'Windows-11-10.0.26200',
  python_version: '3.12.4',
};

function makePendingCrash(overrides: Partial<PendingCrash> = {}): PendingCrash {
  return {
    id: 'server-assigned-id',
    fingerprint: 'fp-show-immediate',
    created_at: '2026-06-28T00:00:00Z',
    exception_type: 'TypeError',
    exception_message: 'cannot read x of undefined',
    trace: ['at fn (app.js:1:1)'],
    hardware: HARDWARE,
    log_tail: [],
    source: 'frontend',
    ...overrides,
  };
}

function dispatchError(message = 'boom'): void {
  window.dispatchEvent(
    new ErrorEvent('error', {
      message,
      error: new Error(message),
      filename: 'errorBoundary.showImmediate.test.ts',
      lineno: 1,
      colno: 1,
    }),
  );
}

/** Drain the promise chain (`.then` → `.finally`) — two ticks is enough. */
async function flushMicrotasks(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('initErrorBoundary — store.showImmediate handoff (regression)', () => {
  let unbind: (() => void) | null = null;

  afterEach(() => {
    unbind?.();
    unbind = null;
    vi.restoreAllMocks();
  });

  it('pushes the resolved PendingCrash into the store via showImmediate', async () => {
    const created = makePendingCrash({
      id: 'returned-from-backend',
      exception_type: 'RuntimeError',
      exception_message: 'wired-modal',
    });
    const report = vi.fn().mockResolvedValue(created);
    const showImmediate = vi.fn();

    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      store: { showImmediate },
      throttleMs: 0,
    });

    dispatchError('boom');
    await flushMicrotasks();

    // The API call must succeed first — sanity-check the seam.
    expect(report).toHaveBeenCalledTimes(1);
    const payload = report.mock.calls[0][0] as CrashReportInput;
    expect(payload.message).toBe('boom');

    // The regression: showImmediate MUST receive the resolved PendingCrash.
    // Without this, +layout.svelte's `#if crashReportsStore.activeImmediate`
    // never flips truthy and CrashDetectionModal stays unmounted even though
    // /api/crash/pending has the row.
    expect(showImmediate).toHaveBeenCalledTimes(1);
    expect(showImmediate).toHaveBeenCalledWith(created);
  });

  it('does NOT call showImmediate when the API call fails (network error)', async () => {
    const showImmediate = vi.fn();
    const report = vi.fn().mockRejectedValue(new Error('network down'));

    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      store: { showImmediate },
      throttleMs: 0,
    });

    dispatchError('boom');
    await flushMicrotasks();

    expect(report).toHaveBeenCalledTimes(1);
    // No PendingCrash exists on a failed POST, so the modal must stay dark
    // (showing an undefined/null crash would crash CrashDetectionModal itself
    // since it dereferences crash.exception_type unconditionally).
    expect(showImmediate).not.toHaveBeenCalled();
  });

  it('does NOT call showImmediate on 403 opt-in-not-completed', async () => {
    // 403 means the user hasn't accepted crash reporting yet. The boundary
    // already handles this as a soft swallow (single console.warn); the modal
    // must NOT pop up because there is no persisted PendingCrash to show.
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const showImmediate = vi.fn();
    const report = vi
      .fn()
      .mockRejectedValue(new ApiError('crash.opt_in_required', 403, 'opt-in required'));

    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      store: { showImmediate },
      throttleMs: 0,
    });

    dispatchError('boom');
    await flushMicrotasks();

    expect(report).toHaveBeenCalledTimes(1);
    expect(showImmediate).not.toHaveBeenCalled();
  });

  it('a throwing showImmediate does not propagate (boundary stays resilient)', async () => {
    // Defensive guarantee: a buggy store implementation must not turn into a
    // second window 'error' event (the re-entrancy guard releases AFTER the
    // promise chain settles, so a `.then` throw would otherwise re-enter).
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const created = makePendingCrash();
    const report = vi.fn().mockResolvedValue(created);
    const showImmediate = vi.fn().mockImplementation(() => {
      throw new Error('store exploded');
    });

    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      store: { showImmediate },
      throttleMs: 0,
    });

    expect(() => dispatchError('boom')).not.toThrow();
    await flushMicrotasks();

    expect(showImmediate).toHaveBeenCalledTimes(1);
    // No second API call — the boundary did not re-enter on the store throw.
    expect(report).toHaveBeenCalledTimes(1);
  });
});

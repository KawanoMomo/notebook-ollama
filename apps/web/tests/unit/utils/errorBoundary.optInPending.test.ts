/**
 * errorBoundary — opt-in-pending queue handoff (Sprint 7 Task 7.3, verify-7.3 fix).
 *
 * Spec §5.9 → "Error-first OptInDialog" path: when `crash_report.enabled === null`
 * (未決定) and an uncaught error fires, the boundary must:
 *
 *   - still skip the POST (mirroring backend's 403 `crash.opt_in_required` —
 *     this is the existing gate, pinned in `errorBoundary.gate.test.ts`), AND
 *
 *   - hand the would-be payload to a `onOptInPending(payload)` callback so the
 *     layout can:
 *       1. queue the error payload,
 *       2. immediately show OptInDialog (without waiting for the 1500ms timer),
 *       3. on accept → drain the queue (POST + showImmediate),
 *       4. on postpone → drop the queue.
 *
 * The callback is the missing seam in the existing gate, which previously just
 * dropped null/false silently. The layout DI's it in; tests cover the wiring.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CrashReportInput } from '$lib/api/crash';
import type { CrashHardware, CrashReportSettings, PendingCrash } from '$lib/api/types';
import { initErrorBoundary } from '$lib/utils/errorBoundary';

// ---------------------------------------------------------------------------
// Fixtures (mirror errorBoundary.gate.test.ts so the test surface stays uniform)
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
    id: 'opt-in-pending-id',
    fingerprint: 'fp-opt-in-pending',
    created_at: '2026-06-29T00:00:00Z',
    exception_type: 'TypeError',
    exception_message: 'opt-in-pending test',
    trace: [],
    hardware: HARDWARE,
    log_tail: [],
    source: 'frontend',
    ...overrides,
  };
}

function makeSettings(
  enabled: boolean | null,
  auto_prompt = true,
): { readonly crashReport: CrashReportSettings } {
  const cr: CrashReportSettings = {
    enabled,
    auto_prompt,
    opted_in_at: enabled === true ? '2026-06-29T00:00:00Z' : null,
  };
  return {
    get crashReport() {
      return cr;
    },
  };
}

function dispatchError(message = 'boom'): void {
  window.dispatchEvent(
    new ErrorEvent('error', {
      message,
      error: new Error(message),
      filename: 'errorBoundary.optInPending.test.ts',
      lineno: 1,
      colno: 1,
    }),
  );
}

async function flushMicrotasks(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('initErrorBoundary — onOptInPending callback (enabled===null short-circuit)', () => {
  let unbind: (() => void) | null = null;

  afterEach(() => {
    unbind?.();
    unbind = null;
    vi.restoreAllMocks();
  });

  it('when enabled===null AND onOptInPending is provided, calls onOptInPending with the would-be payload', async () => {
    const report = vi.fn().mockResolvedValue(makePendingCrash());
    const showImmediate = vi.fn();
    const onOptInPending = vi.fn();

    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      store: { showImmediate },
      settings: makeSettings(null, true),
      onOptInPending,
      throttleMs: 0,
    });

    dispatchError('queue-me');
    await flushMicrotasks();

    expect(onOptInPending).toHaveBeenCalledTimes(1);
    const payload = onOptInPending.mock.calls[0][0] as CrashReportInput;
    expect(payload.message).toBe('queue-me');
    expect(payload.source).toBe('frontend');
    expect(payload.hardware).toBeDefined();

    // No POST and no modal — the OptInDialog takes the floor first.
    expect(report).not.toHaveBeenCalled();
    expect(showImmediate).not.toHaveBeenCalled();
  });

  it('when enabled===false AND onOptInPending is provided, does NOT call onOptInPending (explicit opt-out is final, not a "pending decision")', async () => {
    const report = vi.fn().mockResolvedValue(makePendingCrash());
    const showImmediate = vi.fn();
    const onOptInPending = vi.fn();

    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      store: { showImmediate },
      settings: makeSettings(false, true),
      onOptInPending,
      throttleMs: 0,
    });

    dispatchError('opted-out');
    await flushMicrotasks();

    // Existing gate behaviour preserved: NO POST, NO modal.
    expect(report).not.toHaveBeenCalled();
    expect(showImmediate).not.toHaveBeenCalled();
    // And NO opt-in nag either — false means "the user said no".
    expect(onOptInPending).not.toHaveBeenCalled();
  });

  it('when enabled===true, behaves as the Sprint-5/6 gate (POST → showImmediate); onOptInPending is NOT invoked', async () => {
    const created = makePendingCrash({ id: 'enabled-path' });
    const report = vi.fn().mockResolvedValue(created);
    const showImmediate = vi.fn();
    const onOptInPending = vi.fn();

    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      store: { showImmediate },
      settings: makeSettings(true, true),
      onOptInPending,
      throttleMs: 0,
    });

    dispatchError('post-me');
    await flushMicrotasks();

    expect(report).toHaveBeenCalledTimes(1);
    expect(showImmediate).toHaveBeenCalledWith(created);
    expect(onOptInPending).not.toHaveBeenCalled();
  });

  it('when enabled===null AND onOptInPending is NOT provided, falls back to the silent gate (no POST, no callback)', async () => {
    const report = vi.fn().mockResolvedValue(makePendingCrash());
    const showImmediate = vi.fn();

    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      store: { showImmediate },
      settings: makeSettings(null, true),
      // No onOptInPending — preserves backwards-compat with the gate tests.
      throttleMs: 0,
    });

    dispatchError('silent-drop');
    await flushMicrotasks();

    expect(report).not.toHaveBeenCalled();
    expect(showImmediate).not.toHaveBeenCalled();
  });

  it('opt-in pending short-circuit still respects the same-message throttle', async () => {
    const onOptInPending = vi.fn();
    const report = vi.fn();

    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      settings: makeSettings(null, true),
      onOptInPending,
      throttleMs: 5000,
    });

    dispatchError('same');
    await flushMicrotasks();
    dispatchError('same');
    await flushMicrotasks();
    dispatchError('same');
    await flushMicrotasks();

    expect(onOptInPending).toHaveBeenCalledTimes(1);
    expect(report).not.toHaveBeenCalled();
  });

  it('a throw inside onOptInPending does not propagate or re-enter the handler', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const report = vi.fn();
    const onOptInPending = vi.fn().mockImplementation(() => {
      throw new Error('callback exploded');
    });

    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      settings: makeSettings(null, true),
      onOptInPending,
      throttleMs: 0,
    });

    expect(() => dispatchError('boom')).not.toThrow();
    await flushMicrotasks();

    expect(onOptInPending).toHaveBeenCalledTimes(1);
    // The throw must not have triggered a second window 'error' that re-enters.
    expect(report).not.toHaveBeenCalled();
  });
});

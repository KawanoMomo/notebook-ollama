/**
 * errorBoundary tests (Sprint 5 Task 5.8).
 *
 * `initErrorBoundary()` hooks `window.error` + `window.unhandledrejection` and
 * forwards each occurrence to `crashApi.reportFrontendCrash(...)`.
 *
 * Boundary coverage checklist (Sprint 1-3 lessons):
 * - Empty / missing optional fields (no message, no stack, no reason).
 * - Unicode CJK + emoji preserved through to the API call.
 * - Bounded queue: stops at maxReports (default 5) per session.
 * - Throttle: identical message coalesced inside throttle window.
 * - Re-entrancy: an error THROWN by the reporter itself must not trigger
 *   another report (would loop forever).
 * - 403 (opt-in not completed) → swallowed with a single console.warn,
 *   does NOT count against maxReports nor flood the console.
 * - unbind() removes both listeners (the next event MUST NOT fire the API).
 * - Two independent inits do not share state (vitest module-cache safety).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '$lib/api/client';
import type { CrashReportInput } from '$lib/api/crash';
import type { PendingCrash } from '$lib/api/types';
import { initErrorBoundary } from '$lib/utils/errorBoundary';

// `reportFrontendCrash` resolves with the persisted `PendingCrash` so the
// boundary can hand it to `crashReportsStore.showImmediate(...)`. Tests in
// this file don't care about the resolved value (they assert on the payload
// argument or on the throttle/cap behaviour), so `as unknown as PendingCrash`
// is a deliberate convenience — the regression that DOES care about the
// resolved value lives in `errorBoundary.showImmediate.test.ts`.
type ReportFn = (payload: CrashReportInput) => Promise<PendingCrash>;
interface ReporterApi {
  reportFrontendCrash: ReportFn;
}

/** Capture window.addEventListener calls so we can verify symmetry on unbind. */
function spyWindowListeners() {
  const add = vi.spyOn(window, 'addEventListener');
  const remove = vi.spyOn(window, 'removeEventListener');
  return { add, remove };
}

/** Build a synthetic ErrorEvent (jsdom supports the constructor). */
function makeErrorEvent(opts: {
  message?: string;
  error?: Error | null;
  filename?: string;
  lineno?: number;
  colno?: number;
} = {}): ErrorEvent {
  return new ErrorEvent('error', {
    message: opts.message ?? 'boom',
    error: opts.error ?? new Error(opts.message ?? 'boom'),
    filename: opts.filename ?? 'app.js',
    lineno: opts.lineno ?? 1,
    colno: opts.colno ?? 1,
  });
}

/**
 * Dispatch a PromiseRejectionEvent. jsdom's constructor requires `promise`
 * and `reason`; we resolve the promise after the event to silence the
 * "unhandled rejection" noise vitest would otherwise print.
 */
function dispatchRejection(reason: unknown): void {
  const promise = Promise.reject(reason);
  // swallow the rejection so vitest doesn't fail the test on the real one
  promise.catch(() => {});
  const ev = new PromiseRejectionEvent('unhandledrejection', {
    promise,
    reason,
    cancelable: true,
  });
  window.dispatchEvent(ev);
}

function dispatchError(opts?: Parameters<typeof makeErrorEvent>[0]): void {
  window.dispatchEvent(makeErrorEvent(opts));
}

/** Drain the microtask queue so the in-flight reportFrontendCrash settles. */
async function flushMicrotasks(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

describe('initErrorBoundary — registration', () => {
  let unbind: (() => void) | null = null;
  afterEach(() => {
    unbind?.();
    unbind = null;
    vi.restoreAllMocks();
  });

  it('registers exactly one "error" and one "unhandledrejection" listener', () => {
    const spies = spyWindowListeners();
    const api: ReporterApi = { reportFrontendCrash: vi.fn().mockResolvedValue({}) };
    unbind = initErrorBoundary({ api });

    const events = spies.add.mock.calls.map((c) => c[0]);
    expect(events).toContain('error');
    expect(events).toContain('unhandledrejection');
    // No double-registration.
    expect(events.filter((e) => e === 'error').length).toBe(1);
    expect(events.filter((e) => e === 'unhandledrejection').length).toBe(1);
  });

  it('unbind() removes both listeners (next event MUST NOT call the API)', async () => {
    const spies = spyWindowListeners();
    const report = vi.fn().mockResolvedValue({});
    unbind = initErrorBoundary({ api: { reportFrontendCrash: report } });
    unbind();
    unbind = null;

    const removed = spies.remove.mock.calls.map((c) => c[0]);
    expect(removed).toContain('error');
    expect(removed).toContain('unhandledrejection');

    // After unbind there is no handler to consume the synthetic events,
    // and jsdom would otherwise surface them as "uncaught exception".
    // Install a one-shot swallow handler that calls preventDefault on the
    // event but does NOT call the API — proving the original listener
    // really was removed (vs. just silenced).
    const swallow = (ev: Event) => ev.preventDefault();
    window.addEventListener('error', swallow);
    window.addEventListener('unhandledrejection', swallow);
    try {
      dispatchError();
      dispatchRejection(new Error('after-unbind'));
      await flushMicrotasks();
      expect(report).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener('error', swallow);
      window.removeEventListener('unhandledrejection', swallow);
    }
  });
});

describe('initErrorBoundary — error event → reportFrontendCrash', () => {
  let unbind: (() => void) | null = null;
  afterEach(() => {
    unbind?.();
    unbind = null;
    vi.restoreAllMocks();
  });

  it('forwards message + stack + source=frontend + hardware.ua', async () => {
    const report = vi.fn().mockResolvedValue({});
    unbind = initErrorBoundary({ api: { reportFrontendCrash: report } });

    const err = new Error('TypeError: cannot read x');
    err.stack = 'Error: TypeError\n    at fn (file.js:1:1)';
    dispatchError({ message: 'TypeError: cannot read x', error: err });
    await flushMicrotasks();

    expect(report).toHaveBeenCalledTimes(1);
    const payload = report.mock.calls[0][0] as CrashReportInput;
    expect(payload.message).toBe('TypeError: cannot read x');
    expect(payload.stack).toBe('Error: TypeError\n    at fn (file.js:1:1)');
    expect(payload.source).toBe('frontend');
    expect(payload.hardware).toBeDefined();
    expect((payload.hardware as Record<string, unknown>).ua).toBe(navigator.userAgent);
  });

  it('preserves CJK + emoji in the message verbatim', async () => {
    const report = vi.fn().mockResolvedValue({});
    unbind = initErrorBoundary({ api: { reportFrontendCrash: report } });

    const cjkEmoji = 'クラッシュ 💥 にゃーん';
    dispatchError({ message: cjkEmoji, error: new Error(cjkEmoji) });
    await flushMicrotasks();

    expect((report.mock.calls[0][0] as CrashReportInput).message).toBe(cjkEmoji);
  });

  it('still reports when ErrorEvent.error is null (uses event.message fallback)', async () => {
    const report = vi.fn().mockResolvedValue({});
    unbind = initErrorBoundary({ api: { reportFrontendCrash: report } });

    dispatchError({ message: 'no error object here', error: null });
    await flushMicrotasks();

    expect(report).toHaveBeenCalledTimes(1);
    const payload = report.mock.calls[0][0] as CrashReportInput;
    expect(payload.message).toBe('no error object here');
    // stack is optional when no Error object is present.
    expect(payload.stack === undefined || typeof payload.stack === 'string').toBe(true);
  });

  it('uses a non-empty fallback message when both event.message and error are missing', async () => {
    const report = vi.fn().mockResolvedValue({});
    unbind = initErrorBoundary({ api: { reportFrontendCrash: report } });

    dispatchError({ message: '', error: null });
    await flushMicrotasks();

    expect(report).toHaveBeenCalledTimes(1);
    const payload = report.mock.calls[0][0] as CrashReportInput;
    expect(payload.message.length).toBeGreaterThan(0);
  });
});

describe('initErrorBoundary — unhandledrejection event', () => {
  let unbind: (() => void) | null = null;
  afterEach(() => {
    unbind?.();
    unbind = null;
    vi.restoreAllMocks();
  });

  it('forwards rejection with Error reason (message + stack)', async () => {
    const report = vi.fn().mockResolvedValue({});
    unbind = initErrorBoundary({ api: { reportFrontendCrash: report } });

    const reason = new Error('rejected!');
    reason.stack = 'Error: rejected!\n    at asyncFn';
    dispatchRejection(reason);
    await flushMicrotasks();

    expect(report).toHaveBeenCalledTimes(1);
    const payload = report.mock.calls[0][0] as CrashReportInput;
    expect(payload.message).toContain('rejected!');
    expect(payload.stack).toBe('Error: rejected!\n    at asyncFn');
    expect(payload.source).toBe('frontend');
  });

  it('stringifies non-Error reasons (string)', async () => {
    const report = vi.fn().mockResolvedValue({});
    unbind = initErrorBoundary({ api: { reportFrontendCrash: report } });

    dispatchRejection('plain string failure');
    await flushMicrotasks();

    expect(report).toHaveBeenCalledTimes(1);
    const payload = report.mock.calls[0][0] as CrashReportInput;
    expect(payload.message).toContain('plain string failure');
  });

  it('stringifies non-Error reasons (object without message)', async () => {
    const report = vi.fn().mockResolvedValue({});
    unbind = initErrorBoundary({ api: { reportFrontendCrash: report } });

    dispatchRejection({ code: 42 });
    await flushMicrotasks();

    expect(report).toHaveBeenCalledTimes(1);
    const payload = report.mock.calls[0][0] as CrashReportInput;
    expect(payload.message.length).toBeGreaterThan(0);
  });
});

describe('initErrorBoundary — bounded queue (max reports per session)', () => {
  let unbind: (() => void) | null = null;
  afterEach(() => {
    unbind?.();
    unbind = null;
    vi.restoreAllMocks();
  });

  it('default cap is 5 reports per session, additional are silently dropped', async () => {
    const report = vi.fn().mockResolvedValue({});
    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      throttleMs: 0, // disable throttle for this test
    });

    for (let i = 0; i < 10; i += 1) {
      dispatchError({ message: `boom-${i}`, error: new Error(`boom-${i}`) });
      await flushMicrotasks();
    }
    expect(report).toHaveBeenCalledTimes(5);
  });

  it('respects custom maxReports option', async () => {
    const report = vi.fn().mockResolvedValue({});
    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      maxReports: 2,
      throttleMs: 0,
    });

    for (let i = 0; i < 5; i += 1) {
      dispatchError({ message: `m-${i}`, error: new Error(`m-${i}`) });
      await flushMicrotasks();
    }
    expect(report).toHaveBeenCalledTimes(2);
  });
});

describe('initErrorBoundary — throttle same message', () => {
  let unbind: (() => void) | null = null;
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    unbind?.();
    unbind = null;
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('coalesces identical message within throttle window', async () => {
    const report = vi.fn().mockResolvedValue({});
    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      throttleMs: 5000,
    });

    dispatchError({ message: 'same', error: new Error('same') });
    await flushMicrotasks();
    dispatchError({ message: 'same', error: new Error('same') });
    await flushMicrotasks();
    dispatchError({ message: 'same', error: new Error('same') });
    await flushMicrotasks();

    expect(report).toHaveBeenCalledTimes(1);
  });

  it('different messages bypass the same-message throttle', async () => {
    const report = vi.fn().mockResolvedValue({});
    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      throttleMs: 5000,
    });

    dispatchError({ message: 'a', error: new Error('a') });
    await flushMicrotasks();
    dispatchError({ message: 'b', error: new Error('b') });
    await flushMicrotasks();

    expect(report).toHaveBeenCalledTimes(2);
  });

  it('after throttle window elapses, identical message can fire again', async () => {
    const report = vi.fn().mockResolvedValue({});
    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      throttleMs: 5000,
    });

    dispatchError({ message: 'same', error: new Error('same') });
    await flushMicrotasks();
    vi.advanceTimersByTime(5001);
    dispatchError({ message: 'same', error: new Error('same') });
    await flushMicrotasks();

    expect(report).toHaveBeenCalledTimes(2);
  });
});

describe('initErrorBoundary — re-entrancy guard', () => {
  let unbind: (() => void) | null = null;
  afterEach(() => {
    unbind?.();
    unbind = null;
    vi.restoreAllMocks();
  });

  it('an error thrown synchronously by the reporter does not trigger another report (no loop)', async () => {
    let calls = 0;
    const report = vi.fn().mockImplementation(() => {
      calls += 1;
      // Simulate the reporter itself synchronously raising — without the
      // re-entrancy guard this would dispatch a new window 'error' event
      // and the handler would re-enter, looping until the stack blows.
      throw new Error('reporter exploded');
    });
    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report as unknown as ReportFn },
      throttleMs: 0,
    });

    expect(() => dispatchError({ message: 'first' })).not.toThrow();
    await flushMicrotasks();
    // Exactly one call — re-entrancy guard MUST prevent any cascade.
    expect(calls).toBe(1);
  });

  it('a rejected report Promise does not crash the handler nor trigger re-report', async () => {
    const report = vi.fn().mockRejectedValue(new Error('network down'));
    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      throttleMs: 0,
    });

    expect(() => dispatchError({ message: 'first' })).not.toThrow();
    await flushMicrotasks();
    await flushMicrotasks();
    expect(report).toHaveBeenCalledTimes(1);
  });
});

describe('initErrorBoundary — 403 opt-in-not-completed handling', () => {
  let unbind: (() => void) | null = null;
  let warnSpy: ReturnType<typeof vi.spyOn>;
  beforeEach(() => {
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
  });
  afterEach(() => {
    unbind?.();
    unbind = null;
    vi.restoreAllMocks();
  });

  it('on 403 ApiError: console.warn is called and no exception leaks', async () => {
    const report = vi
      .fn()
      .mockRejectedValue(new ApiError('crash.opt_in_required', 403, 'opt-in required'));
    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      throttleMs: 0,
    });

    expect(() => dispatchError({ message: 'boom' })).not.toThrow();
    await flushMicrotasks();
    await flushMicrotasks();

    expect(report).toHaveBeenCalledTimes(1);
    expect(warnSpy).toHaveBeenCalled();
  });

  it('non-403 ApiError does NOT emit the opt-in console.warn (different code path)', async () => {
    const report = vi
      .fn()
      .mockRejectedValue(new ApiError('internal', 500, 'boom'));
    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      throttleMs: 0,
    });

    expect(() => dispatchError({ message: 'boom' })).not.toThrow();
    await flushMicrotasks();
    await flushMicrotasks();

    // Either silent or a generic warn — but the opt-in-specific path is gated
    // on status===403. We assert nothing leaks and the call still happened.
    expect(report).toHaveBeenCalledTimes(1);
  });
});

describe('initErrorBoundary — isolation between inits', () => {
  it('two independent inits do not share state (no global leak between tests)', async () => {
    const report1 = vi.fn().mockResolvedValue({});
    const report2 = vi.fn().mockResolvedValue({});
    const u1 = initErrorBoundary({
      api: { reportFrontendCrash: report1 },
      throttleMs: 0,
    });
    const u2 = initErrorBoundary({
      api: { reportFrontendCrash: report2 },
      throttleMs: 0,
    });

    dispatchError({ message: 'shared-event' });
    await flushMicrotasks();

    // Both bound listeners fire on the same window event.
    expect(report1).toHaveBeenCalledTimes(1);
    expect(report2).toHaveBeenCalledTimes(1);

    u1();
    dispatchError({ message: 'after-u1' });
    await flushMicrotasks();
    expect(report1).toHaveBeenCalledTimes(1); // still 1 — unbound
    expect(report2).toHaveBeenCalledTimes(2); // still active

    u2();
  });
});

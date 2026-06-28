/**
 * Frontend error boundary — `window.onerror` / `unhandledrejection` → backend.
 *
 * Spec: docs/specs/2026-06-28-crash-report-feedback-hub-design.md §4.1 ③
 * Plan: docs/superpowers/plans/2026-06-28-crash-report-feedback-hub.md Task 5.8
 *
 * Mounted exactly once from `+layout.svelte` `onMount`. On every uncaught
 * exception / unhandled promise rejection, posts a redacted summary to
 * `POST /api/crash/report`. Three safety properties matter:
 *
 *   1. **Re-entrancy guard.** The reporter itself can throw (network down,
 *      JSON serialize bug, etc). Without the guard, that throw would
 *      re-enter `window.error` and we'd loop until the stack blows. We set
 *      a flag while the handler runs and ignore events during that window.
 *
 *   2. **Bounded queue.** A single broken render can fire thousands of
 *      `error` events per second. We cap reports per page-load (default
 *      `MAX_REPORTS = 5`) so a runaway never DoSes the backend.
 *
 *   3. **Same-message throttle.** Identical `message` strings are
 *      coalesced inside `THROTTLE_MS` (default 5s). This complements the
 *      bounded queue: a periodic interval that keeps re-throwing the same
 *      error only ever counts once per window.
 *
 * 403 (`crash.opt_in_required`) is the explicit "user hasn't opted in yet"
 * signal from the backend — we swallow it with a single `console.warn` so
 * it doesn't flood DevTools and doesn't trigger the immediate-modal flow.
 */
import { ApiError } from '$lib/api/client';
import { crashApi, type CrashReportInput } from '$lib/api/crash';
import { crashReportsStore } from '$lib/stores/crashReports.svelte';
import type { PendingCrash } from '$lib/api/types';

/**
 * Minimal API surface the boundary needs. Lets tests inject a mock without
 * having to stub the full `crashApi` module.
 *
 * Tightened to `Promise<PendingCrash>` (vs. `unknown`) so the resolved row
 * can be forwarded to `store.showImmediate(...)` without an unsafe cast.
 */
export interface ErrorBoundaryApi {
  reportFrontendCrash: (payload: CrashReportInput) => Promise<PendingCrash>;
}

/**
 * Minimal store surface — only the seam the boundary needs.
 *
 * Decoupling from the full `CrashReportsStore` interface keeps the test
 * surface tight (no need to stub `load` / `dismiss` / etc. just to verify
 * the modal-mounting handoff) and avoids importing the Svelte $state runtime
 * from a non-component test.
 */
export interface ErrorBoundaryStore {
  /** Mount `CrashDetectionModal` by setting the active immediate slot. */
  showImmediate: (crash: PendingCrash) => void;
}

export interface ErrorBoundaryOptions {
  /** API client (default: real `crashApi`). DI hook for tests. */
  api?: ErrorBoundaryApi;
  /** Crash-reports store (default: real singleton). DI hook for tests. */
  store?: ErrorBoundaryStore;
  /** Max reports per page-load. Default 5. Set 0 to disable. */
  maxReports?: number;
  /** Coalesce identical `message` within this many ms. Default 5000. */
  throttleMs?: number;
}

const DEFAULT_MAX_REPORTS = 5;
const DEFAULT_THROTTLE_MS = 5000;

/** Synthetic fallback for events with no usable message (e.g. blank string). */
const UNKNOWN_MESSAGE = '<unknown error>';

/**
 * Best-effort stringification for non-Error rejection reasons.
 *
 * - `Error` → caller handles `.message` / `.stack` directly; this is only
 *   used for the fallback string path.
 * - `string` / `number` / `bigint` / `boolean` / `symbol` → `String(x)`.
 * - `null` / `undefined` → fallback marker.
 * - object → `JSON.stringify` with a try/catch (circular refs etc.).
 */
function stringifyReason(reason: unknown): string {
  if (reason instanceof Error) return reason.message || UNKNOWN_MESSAGE;
  if (reason === null || reason === undefined) return UNKNOWN_MESSAGE;
  const t = typeof reason;
  if (t === 'string') return (reason as string) || UNKNOWN_MESSAGE;
  if (t === 'number' || t === 'bigint' || t === 'boolean' || t === 'symbol') {
    return String(reason);
  }
  try {
    const s = JSON.stringify(reason);
    return s && s !== '{}' ? s : UNKNOWN_MESSAGE;
  } catch {
    return UNKNOWN_MESSAGE;
  }
}

/**
 * Initialize the error boundary. Returns an `unbind` function that
 * removes the two window listeners. Call exactly once per page-load
 * (typically from `+layout.svelte` `onMount`).
 */
export function initErrorBoundary(options: ErrorBoundaryOptions = {}): () => void {
  const api = options.api ?? crashApi;
  const store = options.store ?? crashReportsStore;
  const maxReports = options.maxReports ?? DEFAULT_MAX_REPORTS;
  const throttleMs = options.throttleMs ?? DEFAULT_THROTTLE_MS;

  // ------- per-init state (a fresh init() does NOT share with prior calls) --
  /** How many reports we've already sent (counts only after the cap check). */
  let reportCount = 0;
  /** Re-entrancy flag — true while we're inside a handler. */
  let reporting = false;
  /** message → last-seen epoch-ms. Used by the throttle. */
  const lastSeen = new Map<string, number>();

  /**
   * Common path for both event types. Synchronous-side enforces the three
   * safety properties; the actual network call is fire-and-forget so we
   * can swallow async failures without leaking them.
   */
  function reportOnce(message: string, stack: string | undefined): void {
    // (1) re-entrancy guard
    if (reporting) return;

    // (2) bounded queue
    if (reportCount >= maxReports) return;

    // (3) same-message throttle
    if (throttleMs > 0) {
      const now = Date.now();
      const prev = lastSeen.get(message);
      if (prev !== undefined && now - prev < throttleMs) return;
      lastSeen.set(message, now);
    }

    reportCount += 1;
    reporting = true;

    const payload: CrashReportInput = {
      message: message || UNKNOWN_MESSAGE,
      source: 'frontend',
      hardware: {
        ua: typeof navigator !== 'undefined' ? navigator.userAgent : '<unavailable>',
      },
    };
    if (stack) payload.stack = stack;

    // Issue the POST inside a try/catch so the reporter NEVER throws
    // synchronously (which would propagate into the original error handler
    // and cascade). We then handle async failure on the returned Promise.
    let pending: Promise<PendingCrash> | null = null;
    try {
      pending = api.reportFrontendCrash(payload);
    } catch (syncErr) {
      // Reporter blew up synchronously. Re-entrancy flag already prevents
      // a cascade; just log to console once and bail.
      // eslint-disable-next-line no-console
      console.warn('[errorBoundary] reporter threw synchronously', syncErr);
      reporting = false;
      return;
    }

    // Async path. Two branches matter:
    //
    //   onFulfilled — the backend persisted the crash and returned the
    //     `PendingCrash`. Hand it to the store so `+layout.svelte`'s
    //     `#if crashReportsStore.activeImmediate` flips truthy and mounts
    //     `CrashDetectionModal` (spec §5.6). Without this push, the modal
    //     never appears even though `/api/crash/pending` has the row —
    //     this was the S4/S5 Playwright regression.
    //
    //   onRejected — translate 403 (opt-in pending) into a single
    //     console.warn instead of a throw; swallow other failures with a
    //     console.warn so we don't loop. We MUST NOT call showImmediate on
    //     this path because there is no PendingCrash to display.
    //
    // `store.showImmediate` is wrapped in its own try/catch: a buggy store
    // must not turn into a "crash report failed" warning (misleading), and
    // it must not leak out of the chain to re-enter the boundary.
    Promise.resolve(pending)
      .then(
        (created) => {
          try {
            store.showImmediate(created);
          } catch (storeErr) {
            // eslint-disable-next-line no-console
            console.warn('[errorBoundary] showImmediate threw', storeErr);
          }
        },
        (err) => {
          if (err instanceof ApiError && err.status === 403) {
            // eslint-disable-next-line no-console
            console.warn(
              '[errorBoundary] crash report skipped: opt-in not completed',
            );
            return;
          }
          // Other failures are swallowed to avoid loops. We log them so a
          // developer running DevTools open notices the silent failure.
          // eslint-disable-next-line no-console
          console.warn('[errorBoundary] crash report failed', err);
        },
      )
      .finally(() => {
        reporting = false;
      });
  }

  function onError(ev: Event): void {
    const e = ev as ErrorEvent;
    const err = e.error instanceof Error ? e.error : null;
    const message = (err?.message ?? e.message ?? '').toString();
    const stack = err?.stack;
    reportOnce(message, stack);
  }

  function onRejection(ev: Event): void {
    const e = ev as PromiseRejectionEvent;
    const reason = e.reason;
    const message =
      reason instanceof Error ? reason.message || UNKNOWN_MESSAGE : stringifyReason(reason);
    const stack = reason instanceof Error ? reason.stack : undefined;
    reportOnce(message, stack);
  }

  window.addEventListener('error', onError);
  window.addEventListener('unhandledrejection', onRejection);

  return () => {
    window.removeEventListener('error', onError);
    window.removeEventListener('unhandledrejection', onRejection);
  };
}

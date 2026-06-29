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
import { settingsStore } from '$lib/stores/settings.svelte';
import type { AppSettings, CrashReportSettings, PendingCrash } from '$lib/api/types';

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

/**
 * Minimal settings surface — only the snapshots the gate needs.
 *
 * Exposed as `readonly` getters so the boundary always sees the latest
 * snapshot at the moment `reportOnce()` runs (mirroring `settingsStore`'s
 * `$derived` accessor — the user can toggle opt-in mid-session and we MUST
 * respect the live value, not a value captured at `initErrorBoundary()` time).
 *
 * `settings` is the raw AppSettings or `null` while the store is still
 * loading. The boundary needs to distinguish "still loading" from "user is
 * undecided" — both surface as `crashReport.enabled === null` (because the
 * derived `crashReport` falls back to DEFAULT_CRASH_REPORT when settings is
 * null), but they require opposite responses:
 *
 *   - still loading → silent drop. We genuinely don't know the user's
 *     preference. An uncaught error is generally repeatable; it will fire
 *     again once settings has loaded.
 *   - undecided     → route through `onOptInPending` so the layout can show
 *     OptInDialog (spec §5.9).
 *
 * Optional for backward compat with tests that pre-date this gate (where the
 * mock only stubbed `crashReport`). In production `settingsStore` always
 * satisfies it.
 */
export interface ErrorBoundarySettings {
  readonly crashReport: CrashReportSettings;
  readonly settings?: AppSettings | null;
}

export interface ErrorBoundaryOptions {
  /** API client (default: real `crashApi`). DI hook for tests. */
  api?: ErrorBoundaryApi;
  /** Crash-reports store (default: real singleton). DI hook for tests. */
  store?: ErrorBoundaryStore;
  /**
   * Settings store (default: real singleton). DI hook for tests.
   *
   * The boundary reads `crashReport.enabled` to gate the POST (mirroring the
   * backend's `403 crash.opt_in_required` rule — see `apps/api/routers/crash.py`)
   * and `crashReport.auto_prompt` to gate `store.showImmediate(...)` (spec §7.3:
   * collect-but-don't-popup mode).
   */
  settings?: ErrorBoundarySettings;
  /** Max reports per page-load. Default 5. Set 0 to disable. */
  maxReports?: number;
  /** Coalesce identical `message` within this many ms. Default 5000. */
  throttleMs?: number;
  /**
   * Spec §5.9 "Error-first OptInDialog" sink (verify-7.3 fix).
   *
   * When `crashReport.enabled === null` (未決定) AND this callback is provided,
   * the boundary skips the POST and hands the would-be `CrashReportInput`
   * payload to the callback instead. The layout uses this to queue the
   * payload and immediately show OptInDialog (without waiting for the 1500ms
   * initial-arm timer). On 「有効にする」 it drains the queue (POST →
   * showImmediate); on 「後で決める」 it drops it.
   *
   * Without this callback (Sprint 5/6 default) the gate falls back to silent
   * drop — the existing `errorBoundary.gate.test.ts` behaviour.
   *
   * Throws are caught and `console.warn`-logged so a buggy callback cannot
   * cascade back into `window.error`.
   *
   * NOTE: `enabled === false` (explicit opt-out) does NOT trigger this
   * callback — the user already said no, nagging them with the OptInDialog
   * again would be hostile. They can flip the toggle in 設定 → クラッシュレポート.
   */
  onOptInPending?: (payload: CrashReportInput) => void;
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
  const settings = options.settings ?? settingsStore;
  const maxReports = options.maxReports ?? DEFAULT_MAX_REPORTS;
  const throttleMs = options.throttleMs ?? DEFAULT_THROTTLE_MS;
  const onOptInPending = options.onOptInPending;

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

    // (3) settings gate — read live (see ErrorBoundarySettings docstring).
    //
    //   enabled !== true → user hasn't opted in (null = undecided / false =
    //   explicit opt-out). Skipping the POST mirrors the backend's
    //   `crash.opt_in_required` 403 rule (apps/api/routers/crash.py) so we
    //   don't burn a network round-trip + console.warn per uncaught exception
    //   while the OptInDialog is still pending. We DO NOT count this against
    //   `reportCount` or `lastSeen` for the silent-drop branches because the
    //   gate is a precondition, not a successful report — once the user opts
    //   in mid-session the very next crash should still go through.
    //
    //   Exception: when `enabled === null` AND `onOptInPending` is wired, we
    //   short-circuit through the callback so the layout can queue + show
    //   OptInDialog (spec §5.9, verify-7.3). This branch DOES tick the
    //   throttle so a runaway error loop can't open the dialog 1000×/sec.
    //
    //   IMPORTANT (S7 home-route fix): we must distinguish "settings still
    //   loading" (`settings.settings === null`) from "user is undecided"
    //   (`settings.settings !== null && crashReport.enabled === null`). Both
    //   surface as `crashReport.enabled === null` through the derived
    //   accessor, but only the latter should trigger `onOptInPending`. The
    //   former is a transient race window between layout mount and load
    //   resolution — we silent-drop the crash here (it'll fire again once
    //   settings loads, since uncaught exceptions are generally repeatable)
    //   rather than (a) hammer the backend with a POST whose preference we
    //   don't know or (b) incorrectly re-prompt an already opted-in user
    //   with OptInDialog. The production cure for this race is the eager
    //   `void settingsStore.load()` in `+layout.svelte`'s `onMount`; this
    //   gate is defense-in-depth in case that load is ever regressed.
    if (settings.settings === null) {
      return;
    }
    const crashSettings = settings.crashReport;
    if (crashSettings.enabled === null && onOptInPending) {
      // same-message throttle (only for this branch — silent drops below
      // intentionally bypass it so an opted-out user can re-enable later
      // without "the first 5s of identical errors are eaten").
      if (throttleMs > 0) {
        const now = Date.now();
        const prev = lastSeen.get(message);
        if (prev !== undefined && now - prev < throttleMs) return;
        lastSeen.set(message, now);
      }
      const payload: CrashReportInput = {
        message: message || UNKNOWN_MESSAGE,
        source: 'frontend',
        hardware: {
          ua: typeof navigator !== 'undefined' ? navigator.userAgent : '<unavailable>',
        },
      };
      if (stack) payload.stack = stack;
      try {
        onOptInPending(payload);
      } catch (cbErr) {
        // eslint-disable-next-line no-console
        console.warn('[errorBoundary] onOptInPending threw', cbErr);
      }
      return;
    }
    if (crashSettings.enabled !== true) return;

    // (4) same-message throttle
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
          // Re-read settings — the user may have toggled `auto_prompt` while
          // the POST was in flight. Spec §7.3: `auto_prompt === false` means
          // "collect crashes silently; I'll review them from the 不具合 tab"
          // — the POST still lands so the row appears in the feedback hub,
          // but `CrashDetectionModal` must stay dark.
          if (settings.crashReport.auto_prompt !== true) return;
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

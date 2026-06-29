/**
 * errorBoundary settings-gate tests (Sprint 7 — opt-in / auto_prompt gating).
 *
 * BACKEND CONTRACT
 * ----------------
 * `apps/api/routers/crash.py::report_crash` now rejects POST /api/crash/report
 * with `403 crash.opt_in_required` whenever `ctx.config.crash_report.enabled
 * is not True`. Hammering the backend with frontend crashes that we know are
 * going to 403 wastes a network round-trip per uncaught exception and floods
 * DevTools with `[errorBoundary] crash report skipped: opt-in not completed`
 * console.warns.
 *
 * The fix is FE-side: gate `reportOnce()` on the live `settingsStore`
 * snapshot BEFORE we issue the POST, mirroring the backend rule. The store
 * is injected via the same DI seam as `crashReportsStore`, so tests do not
 * touch the singleton.
 *
 * FOUR COMBINATIONS (the truth table this file pins)
 * --------------------------------------------------
 *   enabled    | auto_prompt | POST? | showImmediate?
 *   -----------+-------------+-------+----------------
 *   null       | (any)       | NO    | NO
 *   false      | (any)       | NO    | NO
 *   true       | false       | YES   | NO   ← user can still review via 不具合タブ
 *   true       | true        | YES   | YES  ← original behaviour
 *
 * `enabled === null` is "未決定" (the OptInDialog has not been answered yet)
 * and `false` is an explicit opt-out — both must skip POST so the boundary
 * does not race the dialog. `auto_prompt === false` is the "I want crash
 * reports collected but don't pop a modal in my face every time" preference
 * (spec §7.3): the row still lands in `pending_store` so the user can browse
 * it from the feedback hub's 不具合 tab, but `CrashDetectionModal` stays dark.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CrashReportInput } from '$lib/api/crash';
import type { CrashHardware, CrashReportSettings, PendingCrash } from '$lib/api/types';
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
    id: 'gate-test-id',
    fingerprint: 'fp-gate',
    created_at: '2026-06-29T00:00:00Z',
    exception_type: 'TypeError',
    exception_message: 'gate-test message',
    trace: ['at fn (app.js:1:1)'],
    hardware: HARDWARE,
    log_tail: [],
    source: 'frontend',
    ...overrides,
  };
}

/**
 * Build a minimal `ErrorBoundarySettings`-shaped object. The boundary only
 * reads `crashReport.enabled` and `crashReport.auto_prompt`; everything else
 * is ignored. Using a getter (vs. a plain value) mirrors how `settingsStore`
 * exposes `crashReport` as a `$derived` reactive accessor — so the boundary
 * always sees the latest snapshot at the moment `reportOnce()` runs, not a
 * value captured at `initErrorBoundary()` time.
 */
function makeSettings(
  enabled: boolean | null,
  auto_prompt: boolean,
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
      filename: 'errorBoundary.gate.test.ts',
      lineno: 1,
      colno: 1,
    }),
  );
}

/** Drain `.then` → `.finally`. Three ticks beats the chain we install. */
async function flushMicrotasks(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

// ---------------------------------------------------------------------------
// Tests — one block per row in the truth table.
// ---------------------------------------------------------------------------

describe('initErrorBoundary — settings gate (enabled / auto_prompt)', () => {
  let unbind: (() => void) | null = null;

  afterEach(() => {
    unbind?.();
    unbind = null;
    vi.restoreAllMocks();
  });

  // ── Row 1: enabled === null (未決定) ────────────────────────────────────
  it('enabled=null + auto_prompt=true → does NOT POST and does NOT showImmediate', async () => {
    const report = vi
      .fn<(payload: CrashReportInput) => Promise<PendingCrash>>()
      .mockResolvedValue(makePendingCrash());
    const showImmediate = vi.fn();

    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      store: { showImmediate },
      settings: makeSettings(null, true),
      throttleMs: 0,
    });

    dispatchError('undecided');
    await flushMicrotasks();

    // The OptInDialog owns the conversation right now; the boundary must not
    // race it by hammering /api/crash/report (would 403) or by popping its
    // own modal on top of the dialog.
    expect(report).not.toHaveBeenCalled();
    expect(showImmediate).not.toHaveBeenCalled();
  });

  it('enabled=null + auto_prompt=false → does NOT POST and does NOT showImmediate', async () => {
    const report = vi
      .fn<(payload: CrashReportInput) => Promise<PendingCrash>>()
      .mockResolvedValue(makePendingCrash());
    const showImmediate = vi.fn();

    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      store: { showImmediate },
      settings: makeSettings(null, false),
      throttleMs: 0,
    });

    dispatchError('undecided-quiet');
    await flushMicrotasks();

    expect(report).not.toHaveBeenCalled();
    expect(showImmediate).not.toHaveBeenCalled();
  });

  // ── Row 2: enabled === false (明示オプトアウト) ───────────────────────
  it('enabled=false + auto_prompt=true → does NOT POST and does NOT showImmediate', async () => {
    const report = vi
      .fn<(payload: CrashReportInput) => Promise<PendingCrash>>()
      .mockResolvedValue(makePendingCrash());
    const showImmediate = vi.fn();

    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      store: { showImmediate },
      settings: makeSettings(false, true),
      throttleMs: 0,
    });

    dispatchError('opted-out');
    await flushMicrotasks();

    // Explicit opt-out: backend would 403; FE must respect the user's "no".
    expect(report).not.toHaveBeenCalled();
    expect(showImmediate).not.toHaveBeenCalled();
  });

  it('enabled=false + auto_prompt=false → does NOT POST and does NOT showImmediate', async () => {
    const report = vi
      .fn<(payload: CrashReportInput) => Promise<PendingCrash>>()
      .mockResolvedValue(makePendingCrash());
    const showImmediate = vi.fn();

    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      store: { showImmediate },
      settings: makeSettings(false, false),
      throttleMs: 0,
    });

    dispatchError('opted-out-quiet');
    await flushMicrotasks();

    expect(report).not.toHaveBeenCalled();
    expect(showImmediate).not.toHaveBeenCalled();
  });

  // ── Row 3: enabled=true + auto_prompt=false ─────────────────────────────
  it('enabled=true + auto_prompt=false → POSTs but does NOT showImmediate', async () => {
    const created = makePendingCrash({
      id: 'opt-in-quiet',
      exception_message: 'opted in, quiet mode',
    });
    const report = vi
      .fn<(payload: CrashReportInput) => Promise<PendingCrash>>()
      .mockResolvedValue(created);
    const showImmediate = vi.fn();

    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      store: { showImmediate },
      settings: makeSettings(true, false),
      throttleMs: 0,
    });

    dispatchError('opted in, quiet mode');
    await flushMicrotasks();

    // POST happens so the user can review the crash from the 不具合 tab.
    expect(report).toHaveBeenCalledTimes(1);
    const payload = report.mock.calls[0][0] as CrashReportInput;
    expect(payload.message).toBe('opted in, quiet mode');

    // But no modal popup — that's the whole point of auto_prompt=false.
    expect(showImmediate).not.toHaveBeenCalled();
  });

  // ── Row 4: enabled=true + auto_prompt=true (original behaviour) ─────────
  it('enabled=true + auto_prompt=true → POST + showImmediate (regression: original behaviour preserved)', async () => {
    const created = makePendingCrash({
      id: 'full-flow',
      exception_message: 'opted in, prompt on',
    });
    const report = vi
      .fn<(payload: CrashReportInput) => Promise<PendingCrash>>()
      .mockResolvedValue(created);
    const showImmediate = vi.fn();

    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      store: { showImmediate },
      settings: makeSettings(true, true),
      throttleMs: 0,
    });

    dispatchError('opted in, prompt on');
    await flushMicrotasks();

    expect(report).toHaveBeenCalledTimes(1);
    expect(showImmediate).toHaveBeenCalledTimes(1);
    expect(showImmediate).toHaveBeenCalledWith(created);
  });

  // ── Loading state: settings === null is NOT the same as "undecided" ───
  //
  // S7 home-route regression (verify-7.3): on routes that don't call
  // `settingsStore.load()` themselves (e.g. `/`), `settings === null` for the
  // whole session. The derived `crashReport` falls back to DEFAULT_CRASH_REPORT
  // which has `enabled: null` — but that's "still loading", not "user is
  // undecided". The boundary MUST NOT route through `onOptInPending` here:
  //
  //   - For an already opted-in user it would (incorrectly) open OptInDialog,
  //     and the crash POST/CrashDetectionModal would never happen
  //     (the S7 evaluator's "CrashDetectionModal が出ない" complaint).
  //   - For an undecided user the result is correct by accident — but only
  //     because the OptInDialog would also appear via the layout's eager
  //     load + $effect arm. The boundary firing onOptInPending here would
  //     double-mount on top of the timer-armed dialog (latest-wins overwrites
  //     the queue and the user gets two prompts in a row).
  //
  // Production fix (the load): `+layout.svelte` now calls
  // `void settingsStore.load()` from its `onMount`, so `settings === null`
  // resolves quickly. This boundary gate is defense-in-depth for the race
  // window between mount and load resolution, and to fail closed if the
  // eager load is ever regressed.
  it('settings===null (still loading) → silent drop even when onOptInPending is wired (no POST, no callback)', async () => {
    const report = vi
      .fn<(payload: CrashReportInput) => Promise<PendingCrash>>()
      .mockResolvedValue(makePendingCrash());
    const showImmediate = vi.fn();
    const onOptInPending = vi.fn();

    // Mirror the live `settingsStore` shape during the load window: `settings`
    // is null, and the derived `crashReport` falls back to DEFAULT (enabled=null).
    const settings = {
      settings: null,
      get crashReport(): CrashReportSettings {
        return { enabled: null, auto_prompt: true, opted_in_at: null };
      },
    };

    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      store: { showImmediate },
      settings,
      onOptInPending,
      throttleMs: 0,
    });

    dispatchError('home-route-no-load');
    await flushMicrotasks();

    expect(report).not.toHaveBeenCalled();
    expect(showImmediate).not.toHaveBeenCalled();
    // The critical assertion: onOptInPending must NOT fire for "still loading".
    // Without the gate, this would (incorrectly) open OptInDialog on `/`
    // for users who are actually opted in (backend has enabled=true persisted).
    expect(onOptInPending).not.toHaveBeenCalled();
  });

  // ── Reactivity: the boundary must re-read settings on every event ──────
  it('re-reads settings on each event (toggle false → true between dispatches)', async () => {
    // Spec §7.3: the user can flip the toggle in 設定 → クラッシュレポート
    // mid-session. Without re-reading, an init() called while opted-out
    // would silently stay opted-out for the rest of the page-load even after
    // the user opts in. Using a getter (mirroring the $derived in
    // settingsStore) lets us verify the boundary respects the live value.
    let enabled: boolean | null = false;
    const settings = {
      get crashReport(): CrashReportSettings {
        return {
          enabled,
          auto_prompt: true,
          opted_in_at: enabled === true ? '2026-06-29T00:00:00Z' : null,
        };
      },
    };
    const report = vi
      .fn<(payload: CrashReportInput) => Promise<PendingCrash>>()
      .mockResolvedValue(makePendingCrash());
    const showImmediate = vi.fn();

    unbind = initErrorBoundary({
      api: { reportFrontendCrash: report },
      store: { showImmediate },
      settings,
      throttleMs: 0,
    });

    dispatchError('before-opt-in');
    await flushMicrotasks();
    expect(report).not.toHaveBeenCalled();

    // User flips the toggle.
    enabled = true;
    dispatchError('after-opt-in');
    await flushMicrotasks();
    expect(report).toHaveBeenCalledTimes(1);
    expect(showImmediate).toHaveBeenCalledTimes(1);
  });
});

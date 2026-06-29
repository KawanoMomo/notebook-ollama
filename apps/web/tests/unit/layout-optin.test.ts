/**
 * +layout.svelte — OptInDialog orchestration (Sprint 7 Task 7.3, verify-7.3 fix).
 *
 * verify-7.3 identified three regressions in the initial Task 7.3 implementation
 * that this file pins shut:
 *
 *   1. **Slow settings load (>1500ms).** The original one-shot `setTimeout` ran
 *      at 1500ms regardless of whether settings had loaded yet. If settings
 *      took longer, the `if (settings === null) return` early-exit meant the
 *      dialog never appeared at all for the rest of the session. We must
 *      re-arm whenever settings flips into a "loaded + undecided" state.
 *
 *   2. **Re-arm on settings flip.** When settings transitions from `null` to
 *      a loaded value with `crash_report.enabled === null`, the dialog must
 *      schedule its 1500ms appearance from that moment. If settings flips to
 *      `enabled !== null` first, any pending timer must be cancelled.
 *
 *   3. **Error-first queue + drain.** When settings is loaded with `enabled ===
 *      null` AND an uncaught error fires before the timer, the layout must
 *      open OptInDialog immediately and queue the payload. On 「有効にする」
 *      the queue drains (POST → showImmediate → CrashDetectionModal). On
 *      「後で決める」 the queue is dropped.
 *
 * Mocking strategy
 * ----------------
 * `settingsStore` is a module-level singleton. We replace it with a fresh
 * `createSettingsStore(mockApi)` per test via `vi.mock` + a re-assignable
 * `storeRef` (`vi.hoisted` so the factory can see it), so each test sees a
 * clean `settings === null` starting state and we can drive `load()`
 * deterministically.
 *
 * `errorBoundary` is partially mocked: we spy on `initErrorBoundary` to
 * capture the layout's `getOptInState` / `onOptInPending` callbacks so we
 * can drive the error-first path synchronously without having to plumb
 * through `crashApi.reportFrontendCrash` (the layout owns that replay).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { createRawSnippet, tick } from 'svelte';

// ---------------------------------------------------------------------------
// Mocks — `vi.mock` factories are hoisted ABOVE imports, so anything they
// reference must live in `vi.hoisted` to be initialised first.
// ---------------------------------------------------------------------------

const h = vi.hoisted(() => ({
  settingsApiMock: {
    get: vi.fn(),
    stats: vi.fn(),
    putCrashReport: vi.fn(),
    putOllama: vi.fn(),
    putAudio: vi.fn(),
    switchEmbedding: vi.fn(),
  },
  crashApiMock: {
    reportFrontendCrash: vi.fn(),
    listPending: vi.fn().mockResolvedValue([]),
    dismiss: vi.fn().mockResolvedValue(undefined),
    markReported: vi.fn().mockResolvedValue(undefined),
    getPrefillUrl: vi.fn(),
  },
  feedbackHubApiMock: {
    listNotices: vi.fn().mockResolvedValue([]),
    unreadCount: vi.fn().mockResolvedValue({ count: 0 }),
    submitFeedback: vi.fn(),
  },
  // The current per-test settingsStore. The vi.mock factory exposes
  // `settingsStore` as a getter so live-binding always points at the
  // freshest instance.
  storeRef: { current: null as unknown },
  // Captured errorBoundary options. Tests drive the error-first path by
  // invoking `current.onOptInPending(payload)` directly.
  capturedEBOptsRef: { current: null as unknown },
}));

vi.mock('$app/navigation', () => ({ afterNavigate: vi.fn() }));

vi.mock('$lib/api/settings', () => ({
  settingsApi: h.settingsApiMock,
}));

vi.mock('$lib/stores/settings.svelte', async () => {
  const actual = await vi.importActual<typeof import('$lib/stores/settings.svelte')>(
    '$lib/stores/settings.svelte',
  );
  return {
    ...actual,
    get settingsStore() {
      return h.storeRef.current;
    },
  };
});

vi.mock('$lib/api/crash', async () => {
  const actual = await vi.importActual<typeof import('$lib/api/crash')>(
    '$lib/api/crash',
  );
  return { ...actual, crashApi: h.crashApiMock };
});

// Mock feedbackHub so `noticesStore.load()` in `handleOptInDecide` doesn't
// hit a real fetch (which returns `{}` and crashes the `items.filter(...)`
// derived). We return an empty Notice[] which lets the store hydrate
// cleanly.
vi.mock('$lib/api/feedbackHub', () => ({
  feedbackHubApi: h.feedbackHubApiMock,
}));

type EBOpts = import('$lib/utils/errorBoundary').ErrorBoundaryOptions;
vi.mock('$lib/utils/errorBoundary', () => ({
  initErrorBoundary: (opts: EBOpts = {}) => {
    h.capturedEBOptsRef.current = opts;
    return () => {
      h.capturedEBOptsRef.current = null;
    };
  },
}));

// Imports AFTER vi.mock so they pick up the mocked modules.
import { createSettingsStore } from '$lib/stores/settings.svelte';
import { crashReportsStore } from '$lib/stores/crashReports.svelte';
import type { AppSettings, CrashReportSettings, Stats } from '$lib/api/types';
import type { CrashReportInput } from '$lib/api/crash';
import Layout from '../../src/routes/+layout.svelte';

// Convenience accessors after the mocks are wired.
const settingsApiMock = h.settingsApiMock;
const crashApiMock = h.crashApiMock;
const capturedEBOpts = () => h.capturedEBOptsRef.current as EBOpts | null;

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const FULL_SETTINGS_UNDECIDED: AppSettings = {
  ollama: {
    endpoint: 'http://localhost:11434',
    default_model: 'llama3',
    embedding_model: 'nomic-embed-text',
    embedding_dim: 768,
  },
  generation: { context_budget_ratio: 0.5, response_budget_tokens: 2048 },
  retrieval: { top_k: 5, top_k_max: 10, min_history_turns: 1 },
  audio: {
    mic_device_index: null,
    system_device_index: null,
    whisper_model: 'medium',
    device: 'cuda',
    compute_type: 'float16',
    live_caption_default: false,
    agc_enabled: false,
    diarization_enabled: false,
    max_speakers: null,
    voiceprint_naming: false,
    name_inference_llm: false,
    name_threshold: 0.5,
    storage_format: 'opus',
    storage_bitrate_kbps: 96,
    keep_audio: true,
    auto_title: true,
  },
  crash_report: {
    enabled: null,
    auto_prompt: true,
    opted_in_at: null,
  },
};

const STATS_PLACEHOLDER: Stats = {
  notebook_count: 0,
  source_count: 0,
  chunk_count: 0,
  data_dir: '/tmp',
};

function withCrashReport(cr: CrashReportSettings): AppSettings {
  return { ...FULL_SETTINGS_UNDECIDED, crash_report: cr };
}

function renderLayout() {
  const children = createRawSnippet(() => ({
    render: () => '<div data-testid="layout-children">child-content</div>',
  }));
  return render(Layout, { children });
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.useFakeTimers();
  settingsApiMock.get.mockReset();
  settingsApiMock.stats.mockReset();
  settingsApiMock.putCrashReport.mockReset();
  settingsApiMock.putOllama.mockReset();
  crashApiMock.reportFrontendCrash.mockReset();
  h.capturedEBOptsRef.current = null;
  h.storeRef.current = createSettingsStore(settingsApiMock as never);
  crashReportsStore.clearImmediate();
  crashReportsStore.clearPreview();
});

afterEach(() => {
  cleanup();
  crashReportsStore.clearImmediate();
  crashReportsStore.clearPreview();
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// 1. Slow settings load (>1500ms)
// ---------------------------------------------------------------------------

describe('+layout — slow settings load (>1500ms) still arms OptInDialog', () => {
  it('does NOT open OptInDialog at 1500ms when settings is still loading', async () => {
    // Hang the load() so settings stays null past 1500ms.
    settingsApiMock.get.mockReturnValue(new Promise(() => {}));
    settingsApiMock.stats.mockReturnValue(new Promise(() => {}));
    renderLayout();

    await vi.advanceTimersByTimeAsync(2000);
    await tick();

    expect(screen.queryByRole('heading', { name: 'クラッシュレポート機能' })).toBeNull();
  });

  it('opens OptInDialog 1500ms AFTER a slow settings load completes with enabled===null', async () => {
    let resolveGet!: (v: AppSettings) => void;
    let resolveStats!: (v: Stats) => void;
    settingsApiMock.get.mockReturnValue(new Promise((r) => (resolveGet = r)));
    settingsApiMock.stats.mockReturnValue(new Promise((r) => (resolveStats = r)));

    renderLayout();
    // Kick off the load — it's still pending.
    const store = h.storeRef.current as ReturnType<typeof createSettingsStore>;
    const loadPromise = store.load();

    // 3 seconds elapse — way past 1500ms — but settings hasn't loaded yet.
    await vi.advanceTimersByTimeAsync(3000);
    await tick();
    expect(screen.queryByRole('heading', { name: 'クラッシュレポート機能' })).toBeNull();

    // Settings load completes with enabled===null.
    resolveGet(FULL_SETTINGS_UNDECIDED);
    resolveStats(STATS_PLACEHOLDER);
    await loadPromise;
    await tick();

    // Advance through the post-load 1500ms arm.
    await vi.advanceTimersByTimeAsync(1500);
    await tick();

    expect(
      await screen.findByRole('heading', { name: 'クラッシュレポート機能' }),
    ).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// 2. Re-arm via $effect (cancel when settings flips non-null first)
// ---------------------------------------------------------------------------

describe('+layout — re-arm semantics (cancel when settings flips non-null)', () => {
  it('does NOT open OptInDialog when settings loads with enabled===true (already opted in)', async () => {
    settingsApiMock.get.mockResolvedValue(
      withCrashReport({ enabled: true, auto_prompt: true, opted_in_at: '2026-06-28T00:00:00Z' }),
    );
    settingsApiMock.stats.mockResolvedValue(STATS_PLACEHOLDER);

    renderLayout();
    const store = h.storeRef.current as ReturnType<typeof createSettingsStore>;
    await store.load();
    await tick();
    await vi.advanceTimersByTimeAsync(5000);
    await tick();

    expect(screen.queryByRole('heading', { name: 'クラッシュレポート機能' })).toBeNull();
  });

  it('does NOT open OptInDialog when settings loads with enabled===false (explicit opt-out)', async () => {
    settingsApiMock.get.mockResolvedValue(
      withCrashReport({ enabled: false, auto_prompt: true, opted_in_at: '2026-06-28T00:00:00Z' }),
    );
    settingsApiMock.stats.mockResolvedValue(STATS_PLACEHOLDER);

    renderLayout();
    const store = h.storeRef.current as ReturnType<typeof createSettingsStore>;
    await store.load();
    await tick();
    await vi.advanceTimersByTimeAsync(5000);
    await tick();

    expect(screen.queryByRole('heading', { name: 'クラッシュレポート機能' })).toBeNull();
  });

  it('opens OptInDialog 1500ms after settings loads with enabled===null', async () => {
    settingsApiMock.get.mockResolvedValue(FULL_SETTINGS_UNDECIDED);
    settingsApiMock.stats.mockResolvedValue(STATS_PLACEHOLDER);

    renderLayout();
    const store = h.storeRef.current as ReturnType<typeof createSettingsStore>;
    await store.load();
    await tick();

    // Before 1500ms elapses, the dialog must not be visible yet.
    await vi.advanceTimersByTimeAsync(800);
    await tick();
    expect(screen.queryByRole('heading', { name: 'クラッシュレポート機能' })).toBeNull();

    await vi.advanceTimersByTimeAsync(900); // total 1700ms > 1500ms
    await tick();

    expect(
      await screen.findByRole('heading', { name: 'クラッシュレポート機能' }),
    ).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// 3. Error-first queue + drain
// ---------------------------------------------------------------------------

describe('+layout — error-first OptInDialog (queue and drain)', () => {
  it('opens OptInDialog immediately (before 1500ms) when an error fires with enabled===null', async () => {
    settingsApiMock.get.mockResolvedValue(FULL_SETTINGS_UNDECIDED);
    settingsApiMock.stats.mockResolvedValue(STATS_PLACEHOLDER);

    renderLayout();
    const store = h.storeRef.current as ReturnType<typeof createSettingsStore>;
    await store.load();
    await tick();

    // Sanity: the layout wired its `onOptInPending` callback into
    // initErrorBoundary. The boundary's settings gate provides the
    // 'undecided' decision via the live `settings.crashReport.enabled`
    // snapshot — the layout itself doesn't need a separate getOptInState.
    const opts = capturedEBOpts();
    expect(opts).not.toBeNull();
    expect(opts!.onOptInPending).toBeDefined();

    // Simulate a frontend error firing through the boundary's short-circuit.
    const payload: CrashReportInput = {
      message: 'queued-error',
      source: 'frontend',
      hardware: { ua: 'test-agent' },
    };
    opts!.onOptInPending!(payload);
    await tick();

    // Dialog appears NOW, not at 1500ms.
    expect(
      await screen.findByRole('heading', { name: 'クラッシュレポート機能' }),
    ).toBeTruthy();
  });

  it('on 「有効にする」 the queued payload is POSTed and CrashDetectionModal mounts', async () => {
    settingsApiMock.get.mockResolvedValue(FULL_SETTINGS_UNDECIDED);
    settingsApiMock.stats.mockResolvedValue(STATS_PLACEHOLDER);
    settingsApiMock.putCrashReport.mockResolvedValue({
      enabled: true,
      auto_prompt: true,
      opted_in_at: '2026-06-28T00:00:00Z',
    });

    const drainedCrash = {
      id: 'drained-1',
      fingerprint: 'fp-drain',
      created_at: '2026-06-28T00:00:00Z',
      exception_type: 'RuntimeError',
      exception_message: 'queued-error',
      trace: [],
      hardware: {},
      log_tail: [],
      source: 'frontend' as const,
    };
    crashApiMock.reportFrontendCrash.mockResolvedValue(drainedCrash);

    // Stub fetch so the OptInDialog's default PUT path is satisfied too.
    // The component uses its `api` prop (defaulting to fetch) — the layout
    // doesn't override it, so we need a fetch impl that says 200 OK.
    const originalFetch = globalThis.fetch;
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    try {
      renderLayout();
      const store = h.storeRef.current as ReturnType<typeof createSettingsStore>;
      await store.load();
      await tick();

      // Queue an error.
      const payload: CrashReportInput = {
        message: 'queued-error',
        source: 'frontend',
        hardware: { ua: 'test-agent' },
      };
      const opts = capturedEBOpts();
      opts!.onOptInPending!(payload);
      await tick();

      // Re-load on accept should return the new (enabled=true) settings.
      settingsApiMock.get.mockResolvedValue(
        withCrashReport({ enabled: true, auto_prompt: true, opted_in_at: '2026-06-28T00:00:00Z' }),
      );

      // Click 「有効にする」 — OptInDialog issues its own PUT then onDecide(true).
      const enableBtn = await screen.findByRole('button', { name: '有効にする' });
      await fireEvent.click(enableBtn);

      // Let the dialog's PUT + the layout's drain settle.
      await vi.runAllTimersAsync();
      await tick();
      await tick();

      await waitFor(() => {
        expect(crashApiMock.reportFrontendCrash).toHaveBeenCalledTimes(1);
      });
      const sent = crashApiMock.reportFrontendCrash.mock.calls[0][0] as CrashReportInput;
      expect(sent.message).toBe('queued-error');

      // The drained PendingCrash made it into the showImmediate slot, meaning
      // CrashDetectionModal would mount.
      await waitFor(() => {
        expect(crashReportsStore.activeImmediate?.id).toBe('drained-1');
      });
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('on 「後で決める」 the queued payload is DROPPED (no POST)', async () => {
    settingsApiMock.get.mockResolvedValue(FULL_SETTINGS_UNDECIDED);
    settingsApiMock.stats.mockResolvedValue(STATS_PLACEHOLDER);

    renderLayout();
    const store = h.storeRef.current as ReturnType<typeof createSettingsStore>;
    await store.load();
    await tick();

    const opts = capturedEBOpts();
    opts!.onOptInPending!({
      message: 'queued-error',
      source: 'frontend',
      hardware: {},
    });
    await tick();

    const postponeBtn = await screen.findByRole('button', { name: '後で決める' });
    await fireEvent.click(postponeBtn);
    await vi.runAllTimersAsync();
    await tick();
    await tick();

    expect(crashApiMock.reportFrontendCrash).not.toHaveBeenCalled();
    expect(crashReportsStore.activeImmediate).toBeNull();
  });
});

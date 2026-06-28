/**
 * +layout.svelte wiring tests (Sprint 5 Task 5.8 / 5.7).
 *
 * Visual-verify found that Sprint 5 components (`errorBoundary.ts`,
 * `CrashPreviewDialog.svelte`) ship as orphans: `+layout.svelte`
 * never calls `initErrorBoundary()` and the preview button is a
 * no-op TODO. These integration-style tests pin the wiring so the
 * pipeline cannot regress to "implemented but unmounted" again.
 *
 * Approach
 * --------
 * The layout depends on SvelteKit's `$app/navigation` and a handful
 * of singletons that all share global module state. We:
 *
 *   1. Mock `$app/navigation` so `afterNavigate` is a no-op stub.
 *   2. Spy on `initErrorBoundary` (the actual util at
 *      `$lib/utils/errorBoundary`) so we can both verify it was
 *      called AND observe whether the layout calls its returned
 *      `unbind` on destroy.
 *   3. Use the real `crashReportsStore` singleton so the layout
 *      reactively re-renders on `showImmediate(...)` / `showPreview(...)`.
 *   4. Provide a tiny `<svelte:fragment>`-like children snippet via
 *      `createRawSnippet` so the layout's `{@render children()}`
 *      doesn't blow up.
 *
 * The "fetch is called when an error is dispatched" assertion is
 * the smoking gun for the orphan-util bug: if `initErrorBoundary`
 * is never invoked, no `window.error` listener is registered, and
 * `fetch` never sees `/api/crash/report`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { createRawSnippet, tick } from 'svelte';

// ---------------------------------------------------------------------------
// Mocks — must be declared before importing the layout so vitest can
// intercept the `$app/navigation` and `$lib/utils/errorBoundary` imports.
// ---------------------------------------------------------------------------

vi.mock('$app/navigation', () => ({
  afterNavigate: vi.fn(),
}));

// Real init/teardown lives in errorBoundary.ts. We spy on it (instead
// of fully replacing) so the test still exercises the real listener
// registration code path against window.
const initSpy = vi.fn();
const teardownSpy = vi.fn();

vi.mock('$lib/utils/errorBoundary', async () => {
  const actual = await vi.importActual<typeof import('$lib/utils/errorBoundary')>(
    '$lib/utils/errorBoundary',
  );
  return {
    ...actual,
    initErrorBoundary: (...args: Parameters<typeof actual.initErrorBoundary>) => {
      initSpy(...args);
      const unbind = actual.initErrorBoundary(...args);
      // Wrap the returned unbind so we can verify the layout actually calls it.
      return () => {
        teardownSpy();
        unbind();
      };
    },
  };
});

import Layout from '../../src/routes/+layout.svelte';
import { crashReportsStore } from '$lib/stores/crashReports.svelte';
import type { CrashHardware, PendingCrash } from '$lib/api/types';

// ---------------------------------------------------------------------------
// Fixtures & helpers
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

function makeCrash(overrides: Partial<PendingCrash> = {}): PendingCrash {
  return {
    id: 'crash-layout-1',
    fingerprint: 'fp-layout-1',
    created_at: '2026-06-28T00:00:00Z',
    exception_type: 'RuntimeError',
    exception_message: 'boom from layout',
    trace: ['at handler (app.js:42:10)'],
    hardware: HARDWARE,
    log_tail: [],
    source: 'frontend',
    ...overrides,
  };
}

/**
 * Renders the layout with a non-empty children snippet. `+layout.svelte`
 * does `{@render children()}` — passing `undefined` would crash the test.
 */
function renderLayout() {
  const children = createRawSnippet(() => ({
    render: () => '<div data-testid="layout-children">child-content</div>',
  }));
  return render(Layout, { children });
}

// ---------------------------------------------------------------------------
// Test-environment shims
// ---------------------------------------------------------------------------

const originalFetch = globalThis.fetch;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  initSpy.mockReset();
  teardownSpy.mockReset();
  // Reset store state between tests so reactivity starts clean.
  crashReportsStore.clearImmediate();
  crashReportsStore.clearPreview();

  fetchMock = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify(makeCrash({ id: 'server-returned-id' })),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ),
  );
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  cleanup();
  crashReportsStore.clearImmediate();
  crashReportsStore.clearPreview();
  globalThis.fetch = originalFetch;
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('+layout.svelte — errorBoundary wiring (Task 5.8)', () => {
  it('calls initErrorBoundary() exactly once on mount', () => {
    renderLayout();
    expect(initSpy).toHaveBeenCalledTimes(1);
  });

  it('initErrorBoundary actually registers a window "error" listener (fetch is called when an error fires)', async () => {
    renderLayout();
    // Pin the regression: the orphan-util bug shows up here because no
    // listener was ever attached, so dispatching the event was a no-op.
    window.dispatchEvent(
      new ErrorEvent('error', {
        message: 'synthetic-from-layout-test',
        error: new Error('synthetic-from-layout-test'),
        filename: 'layout-wiring.test.ts',
        lineno: 1,
        colno: 1,
      }),
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('/api/crash/report');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe('POST');
    const body = JSON.parse(init.body as string) as { message: string; source: string };
    expect(body.message).toBe('synthetic-from-layout-test');
    expect(body.source).toBe('frontend');
  });

  it('calls the unbind returned by initErrorBoundary on destroy', () => {
    const { unmount } = renderLayout();
    expect(teardownSpy).not.toHaveBeenCalled();
    unmount();
    expect(teardownSpy).toHaveBeenCalledTimes(1);
  });
});

describe('+layout.svelte — CrashDetectionModal mounts on activeImmediate', () => {
  it('does NOT render the modal when activeImmediate is null', () => {
    renderLayout();
    expect(screen.queryByRole('alertdialog')).toBeNull();
  });

  it('renders the modal when crashReportsStore.showImmediate(crash) is called', async () => {
    renderLayout();
    crashReportsStore.showImmediate(
      makeCrash({ exception_type: 'TypeError', exception_message: 'wired-modal' }),
    );
    await tick();
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toBeTruthy();
    expect(dialog.textContent).toContain('TypeError');
    expect(dialog.textContent).toContain('wired-modal');
  });
});

describe('+layout.svelte — onPreview wiring (Task 5.7)', () => {
  it('clicking "送信内容をプレビュー →" mounts CrashPreviewDialog (real component, not stub)', async () => {
    // CrashPreviewDialog mounts and calls crashApi.getPrefillUrl on mount,
    // which goes through fetch → we satisfy it with a default JSON response.
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url.includes('/prefill-url')) {
        return new Response(
          JSON.stringify({
            url: 'https://github.com/KawanoMomo/notebook-ollama/issues/new?title=t&body=b&labels=crash-auto',
            truncated: false,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      return new Response('null', { status: 200, headers: { 'Content-Type': 'application/json' } });
    });

    renderLayout();
    crashReportsStore.showImmediate(makeCrash({ id: 'to-preview' }));
    await tick();

    const previewBtn = await screen.findByRole('button', { name: /送信内容をプレビュー/ });
    await fireEvent.click(previewBtn);
    await tick();

    // The store's "previewing" slot is the contract +layout uses to decide
    // whether to mount CrashPreviewDialog.
    expect(crashReportsStore.previewing).not.toBeNull();
    expect(crashReportsStore.previewing?.id).toBe('to-preview');

    // CrashPreviewDialog (the real component) has aria-label
    // "クラッシュレポートのプレビュー" — assert the actual dialog is mounted,
    // not just a stub or a closed CrashDetectionModal.
    const previewDialog = await screen.findByRole('dialog', {
      name: 'クラッシュレポートのプレビュー',
    });
    expect(previewDialog).toBeTruthy();
  });

  it('also clears activeImmediate when preview is opened (the detection modal is replaced)', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          url: 'https://github.com/KawanoMomo/notebook-ollama/issues/new?title=t&body=b&labels=',
          truncated: false,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    renderLayout();
    crashReportsStore.showImmediate(makeCrash({ id: 'to-preview-2' }));
    await tick();

    const previewBtn = await screen.findByRole('button', { name: /送信内容をプレビュー/ });
    await fireEvent.click(previewBtn);
    await tick();

    // Detection modal hand-off: activeImmediate is cleared, previewing is set.
    expect(crashReportsStore.activeImmediate).toBeNull();
    expect(crashReportsStore.previewing).not.toBeNull();
  });
});

describe('crashReports store — previewing slot (Task 5.7 wiring)', () => {
  it('previewing starts as null', () => {
    // Use a fresh import so we don't depend on the singleton's history.
    expect(crashReportsStore.previewing).toBeNull();
  });

  it('showPreview(crash) sets previewing; clearPreview resets it', () => {
    const crash = makeCrash({ id: 'preview-store' });
    crashReportsStore.showPreview(crash);
    expect(crashReportsStore.previewing?.id).toBe('preview-store');
    crashReportsStore.clearPreview();
    expect(crashReportsStore.previewing).toBeNull();
  });
});

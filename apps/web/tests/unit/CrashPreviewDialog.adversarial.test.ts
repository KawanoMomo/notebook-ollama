/**
 * Adversarial probes for CrashPreviewDialog (Sprint 5 Task 5.7 verify).
 *
 * Goals: stress-test failure modes that the existing tests don't cover.
 *   - popup-blocked window.open (returns null) — should NOT silently mark as reported
 *   - dismiss vs GitHub-open race — overlapping API calls
 *   - truncation warning reactivity after user edits the body
 *   - oversize body — does rebuildUrl still succeed; is the user warned?
 *   - backdrop close mid-flight — does onClose get called while a request is in flight?
 *   - Cancel paths (X / Escape / backdrop) MUST NOT call markReported
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';

const getPrefillUrlMock = vi.fn();
const dismissMock = vi.fn();
const markReportedMock = vi.fn();

vi.mock('$lib/api/crash', () => ({
  crashApi: {
    getPrefillUrl: (...a: unknown[]) => getPrefillUrlMock(...a),
    dismiss: (...a: unknown[]) => dismissMock(...a),
    markReported: (...a: unknown[]) => markReportedMock(...a),
    listPending: vi.fn(),
    reportFrontendCrash: vi.fn(),
  },
}));

const pushToastMock = vi.fn();
vi.mock('$lib/components/Toast.svelte', () => ({
  pushToast: (...a: unknown[]) => pushToastMock(...a),
  default: vi.fn(),
}));

import CrashPreviewDialog from '$lib/components/CrashPreviewDialog.svelte';
import type { CrashHardware, PendingCrash } from '$lib/api/types';

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
    id: 'a'.repeat(32),
    fingerprint: 'b'.repeat(40),
    created_at: '2026-06-28T00:00:00Z',
    exception_type: 'RuntimeError',
    exception_message: 'boom',
    trace: ['at handler (app.js:42:10)'],
    hardware: HARDWARE,
    log_tail: [],
    source: 'frontend',
    ...overrides,
  };
}

function buildBackendUrl(opts: { title: string; body: string; labels: string[] }): string {
  const u = new URL('https://github.com/KawanoMomo/notebook-ollama/issues/new');
  u.searchParams.set('title', opts.title);
  u.searchParams.set('body', opts.body);
  u.searchParams.set('labels', opts.labels.join(','));
  return u.toString();
}

function defaultPrefillResponse(over: Partial<{
  title: string;
  body: string;
  labels: string[];
  truncated: boolean;
}> = {}) {
  return {
    url: buildBackendUrl({
      title: over.title ?? '[crash] RuntimeError: boom',
      body: over.body ?? '## 概要\nboom',
      labels: over.labels ?? ['crash-auto'],
    }),
    truncated: over.truncated ?? false,
  };
}

const writeTextMock = vi.fn().mockResolvedValue(undefined);
const openMock = vi.fn();
const originalOpen = globalThis.open;
const originalClipboard = (globalThis.navigator && navigator.clipboard) ?? undefined;

beforeEach(() => {
  getPrefillUrlMock.mockReset().mockResolvedValue(defaultPrefillResponse());
  dismissMock.mockReset().mockResolvedValue(undefined);
  markReportedMock.mockReset().mockResolvedValue(undefined);
  pushToastMock.mockReset();
  writeTextMock.mockReset().mockResolvedValue(undefined);
  openMock.mockReset();
  Object.defineProperty(globalThis.navigator, 'clipboard', {
    value: { writeText: writeTextMock },
    configurable: true,
  });
  globalThis.open = openMock as unknown as typeof globalThis.open;
});

afterEach(() => {
  cleanup();
  if (originalClipboard !== undefined) {
    Object.defineProperty(globalThis.navigator, 'clipboard', {
      value: originalClipboard,
      configurable: true,
    });
  }
  globalThis.open = originalOpen;
});

describe('ADVERSARIAL — popup blocked', () => {
  it('returns null from window.open BUT still marks the crash as reported (DEFECT)', async () => {
    // Browsers return null from window.open when the popup is blocked.
    openMock.mockReturnValueOnce(null);
    const onReportedMock = vi.fn();
    const onCloseMock = vi.fn();
    render(CrashPreviewDialog, {
      crash: makeCrash(),
      onClose: onCloseMock,
      onReported: onReportedMock,
    });
    await screen.findByLabelText('タイトル');
    await fireEvent.click(screen.getByRole('button', { name: 'GitHubで開く →' }));
    await waitFor(() => expect(openMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(markReportedMock).toHaveBeenCalledTimes(1));
    // Captures the defect: user never saw GitHub, but we still recorded "reported".
    expect(onReportedMock).toHaveBeenCalled();
    expect(onCloseMock).toHaveBeenCalled();
    // No user-facing warning that the popup was blocked.
    expect(
      pushToastMock.mock.calls.find((c) => /ポップアップ|popup|blocked|ブロック/i.test(String(c[0]))),
    ).toBeUndefined();
  });
});

describe('ADVERSARIAL — cancel paths must not mark reported', () => {
  it('X close button does NOT call markReported', async () => {
    const onClose = vi.fn();
    render(CrashPreviewDialog, { crash: makeCrash(), onClose });
    await screen.findByLabelText('タイトル');
    await fireEvent.click(screen.getByLabelText('閉じる'));
    expect(markReportedMock).not.toHaveBeenCalled();
    expect(dismissMock).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('Escape does NOT call markReported nor dismiss', async () => {
    const onClose = vi.fn();
    render(CrashPreviewDialog, { crash: makeCrash(), onClose });
    await screen.findByLabelText('タイトル');
    await fireEvent.keyDown(window, { key: 'Escape' });
    await tick();
    expect(markReportedMock).not.toHaveBeenCalled();
    expect(dismissMock).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('Backdrop click does NOT call markReported nor dismiss', async () => {
    const onClose = vi.fn();
    const { container } = render(CrashPreviewDialog, { crash: makeCrash(), onClose });
    await screen.findByLabelText('タイトル');
    const backdrop = container.querySelector('.backdrop')!;
    await fireEvent.click(backdrop);
    expect(markReportedMock).not.toHaveBeenCalled();
    expect(dismissMock).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe('ADVERSARIAL — oversize body builds URL but no client guard', () => {
  it('builds the URL with a huge body even when it dwarfs the 7KB safe limit', async () => {
    // 20KB body — backend would mark truncated, but here we test the FE rebuild path:
    // after the user re-enlarges body locally, the FE has no safety check.
    getPrefillUrlMock.mockResolvedValueOnce({
      url: buildBackendUrl({
        title: '[crash] big',
        body: 'short body',
        labels: ['crash-auto'],
      }),
      truncated: true, // backend already truncated
    });
    render(CrashPreviewDialog, { crash: makeCrash(), onClose: vi.fn() });
    const body = (await screen.findByLabelText('本文')) as HTMLTextAreaElement;
    const huge = 'X'.repeat(20_000);
    await fireEvent.input(body, { target: { value: huge } });
    await fireEvent.click(screen.getByRole('button', { name: 'GitHubで開く →' }));
    await waitFor(() => expect(openMock).toHaveBeenCalledTimes(1));
    const [openUrl] = openMock.mock.calls[0] as [string, string];
    expect(openUrl.length).toBeGreaterThan(20_000); // No length guard; URL is huge.
    // No re-warning toast about exceeding the 8KB safe limit.
    expect(
      pushToastMock.mock.calls.find((c) => /長|long|truncat|切り詰/i.test(String(c[0]))),
    ).toBeUndefined();
  });
});

describe('ADVERSARIAL — truncation warning reactivity', () => {
  it('truncation warning stays visible even after user shrinks the body (stale state)', async () => {
    getPrefillUrlMock.mockResolvedValueOnce(defaultPrefillResponse({ truncated: true }));
    render(CrashPreviewDialog, { crash: makeCrash(), onClose: vi.fn() });
    const body = (await screen.findByLabelText('本文')) as HTMLTextAreaElement;
    expect(screen.getByText(/切り詰め|truncat/i)).toBeTruthy();
    // User shortens body — but the warning won't update because truncated is
    // derived only from the initial backend response.
    await fireEvent.input(body, { target: { value: 'tiny' } });
    expect(screen.queryByText(/切り詰め|truncat/i)).not.toBeNull(); // stale
  });

  it('truncation warning does NOT appear after user enlarges body past 8KB (also stale)', async () => {
    render(CrashPreviewDialog, { crash: makeCrash(), onClose: vi.fn() });
    const body = (await screen.findByLabelText('本文')) as HTMLTextAreaElement;
    expect(screen.queryByText(/切り詰め|truncat/i)).toBeNull();
    await fireEvent.input(body, { target: { value: 'Y'.repeat(20_000) } });
    // The component does NOT re-evaluate truncation — silent oversize.
    expect(screen.queryByText(/切り詰め|truncat/i)).toBeNull();
  });
});

describe('ADVERSARIAL — race conditions', () => {
  it('GitHub open is NOT disabled while dismiss is in flight', async () => {
    // dismiss hangs forever
    let resolveDismiss: () => void = () => {};
    dismissMock.mockReturnValueOnce(new Promise<void>((res) => { resolveDismiss = res; }));
    render(CrashPreviewDialog, { crash: makeCrash(), onClose: vi.fn() });
    await screen.findByLabelText('タイトル');
    const dismissBtn = screen.getByRole('button', { name: '却下' });
    const githubBtn = screen.getByRole('button', { name: 'GitHubで開く →' }) as HTMLButtonElement;
    await fireEvent.click(dismissBtn);
    // dismiss is in flight — but GitHub button is still enabled.
    expect(githubBtn.disabled).toBe(false);
    // User can click GitHub mid-dismiss — both API calls fire on the same id.
    await fireEvent.click(githubBtn);
    await waitFor(() => expect(openMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(markReportedMock).toHaveBeenCalledTimes(1));
    resolveDismiss();
  });

  it('dismiss button is NOT disabled while reporting is in flight', async () => {
    let resolveReport: () => void = () => {};
    markReportedMock.mockReturnValueOnce(
      new Promise<void>((res) => { resolveReport = res; }),
    );
    render(CrashPreviewDialog, { crash: makeCrash(), onClose: vi.fn() });
    await screen.findByLabelText('タイトル');
    const dismissBtn = screen.getByRole('button', { name: '却下' }) as HTMLButtonElement;
    const githubBtn = screen.getByRole('button', { name: 'GitHubで開く →' });
    await fireEvent.click(githubBtn);
    await waitFor(() => expect(openMock).toHaveBeenCalledTimes(1));
    // Now markReported is pending — but dismiss button is still enabled.
    expect(dismissBtn.disabled).toBe(false);
    await fireEvent.click(dismissBtn);
    await waitFor(() => expect(dismissMock).toHaveBeenCalledTimes(1));
    resolveReport();
  });
});

describe('ADVERSARIAL — backdrop click mid-flight', () => {
  it('backdrop click during in-flight markReported still calls onClose (orphan promise)', async () => {
    let resolveReport: () => void = () => {};
    markReportedMock.mockReturnValueOnce(
      new Promise<void>((res) => { resolveReport = res; }),
    );
    const onClose = vi.fn();
    const { container } = render(CrashPreviewDialog, { crash: makeCrash(), onClose });
    await screen.findByLabelText('タイトル');
    await fireEvent.click(screen.getByRole('button', { name: 'GitHubで開く →' }));
    await waitFor(() => expect(openMock).toHaveBeenCalledTimes(1));
    // Click backdrop while markReported is in flight.
    const backdrop = container.querySelector('.backdrop')!;
    await fireEvent.click(backdrop);
    // onClose fires immediately — the in-flight markReported is left to resolve later.
    expect(onClose).toHaveBeenCalledTimes(1);
    resolveReport();
  });
});

/**
 * CrashPreviewDialog tests (Sprint 5 Task 5.7).
 *
 * spec: docs/specs/2026-06-28-crash-report-feedback-hub-design.md §5.7
 * plan: docs/superpowers/plans/2026-06-28-crash-report-feedback-hub.md Task 5.7
 *
 * Scope (matches the in-scope dialog component):
 *   - Loads default prefill URL on mount via crashApi.getPrefillUrl(id) and
 *     parses ?title= / ?body= / ?labels= back into editable form state.
 *   - Renders editable title input, label chips (add/remove), Markdown body
 *     textarea, and the 3 footer buttons (却下 / コピー / GitHubで開く →).
 *   - 却下 → crashApi.dismiss(id) + onDismissed?.(id) + onClose().
 *   - コピー → navigator.clipboard.writeText(body) + success toast (failure
 *     surfaces as an error toast, not an unhandled rejection).
 *   - GitHubで開く → rebuilds the URL with the **edited** title/body/labels
 *     (server-side build_issue_url 相当を FE 側で再現), window.open(url, '_blank'),
 *     crashApi.markReported(id), onReported?.(id), onClose().
 *
 * Boundary coverage (Sprint 1-3 lessons learned):
 *   - Unicode CJK + emoji round-trip through parse → edit → rebuild.
 *   - Empty / missing labels query param yields labels=[] not [''].
 *   - truncated=true surfaces a visible warning in the body section.
 *   - getPrefillUrl failure → no form, visible error, no crash.
 *   - Failures inside dismiss / markReported propagate (caller decides) and
 *     do NOT call onClose so the user can retry.
 *   - Empty new label string is rejected (no whitespace chip added).
 *   - Duplicate label add is no-op (idempotent).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';

// ---------------------------------------------------------------------------
// Module mocks — must be declared before the component import so vitest can
// intercept the `$lib/api/crash` import inside CrashPreviewDialog.svelte.
// ---------------------------------------------------------------------------

const getPrefillUrlMock = vi.fn();
const dismissMock = vi.fn();
const markReportedMock = vi.fn();

vi.mock('$lib/api/crash', () => ({
  crashApi: {
    getPrefillUrl: (...a: unknown[]) => getPrefillUrlMock(...a),
    dismiss: (...a: unknown[]) => dismissMock(...a),
    markReported: (...a: unknown[]) => markReportedMock(...a),
    // Unused by the dialog but kept for shape parity with the real module.
    listPending: vi.fn(),
    reportFrontendCrash: vi.fn(),
  },
}));

const pushToastMock = vi.fn();
vi.mock('$lib/components/Toast.svelte', () => ({
  // Toast.svelte exports `pushToast` from a <script module>. The component
  // default export is never rendered by the dialog — only `pushToast` is
  // imported — so a minimal stub is enough.
  pushToast: (...a: unknown[]) => pushToastMock(...a),
  default: vi.fn(),
}));

import CrashPreviewDialog from '$lib/components/CrashPreviewDialog.svelte';
import type { CrashHardware, PendingCrash } from '$lib/api/types';

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

/**
 * Build a realistic prefill URL exactly like the backend (`prefill_url.py`):
 * application/x-www-form-urlencoded with `+` for spaces, comma-separated labels.
 *
 * Using URLSearchParams here matches the encoder we'll re-use in the
 * dialog itself for URL rebuild, so parse / rebuild are symmetric.
 */
function buildBackendUrl(opts: {
  title: string;
  body: string;
  labels: string[];
}): string {
  const u = new URL('https://github.com/KawanoMomo/notebook-ollama/issues/new');
  u.searchParams.set('title', opts.title);
  u.searchParams.set('body', opts.body);
  u.searchParams.set('labels', opts.labels.join(','));
  return u.toString();
}

const DEFAULT_TITLE = '[crash] RuntimeError: boom';
const DEFAULT_BODY = '## 概要\nRuntimeError: boom\n\n## 環境\n- CPU: Intel\n';
const DEFAULT_LABELS = ['crash-auto', 'needs-triage'];

function defaultPrefillResponse(over: Partial<{
  title: string;
  body: string;
  labels: string[];
  truncated: boolean;
}> = {}) {
  const title = over.title ?? DEFAULT_TITLE;
  const body = over.body ?? DEFAULT_BODY;
  const labels = over.labels ?? DEFAULT_LABELS;
  return {
    url: buildBackendUrl({ title, body, labels }),
    truncated: over.truncated ?? false,
  };
}

function renderDialog(extra: Record<string, unknown> = {}) {
  const onClose = vi.fn();
  const onDismissed = vi.fn();
  const onReported = vi.fn();
  const result = render(CrashPreviewDialog, {
    crash: makeCrash(),
    onClose,
    onDismissed,
    onReported,
    ...extra,
  });
  return { ...result, onClose, onDismissed, onReported };
}

// ---------------------------------------------------------------------------
// Test environment shims
// ---------------------------------------------------------------------------

const originalClipboard = (globalThis.navigator && navigator.clipboard) ?? undefined;
const originalOpen = globalThis.open;
const writeTextMock = vi.fn().mockResolvedValue(undefined);
const openMock = vi.fn();

beforeEach(() => {
  getPrefillUrlMock.mockReset().mockResolvedValue(defaultPrefillResponse());
  dismissMock.mockReset().mockResolvedValue(undefined);
  markReportedMock.mockReset().mockResolvedValue(undefined);
  pushToastMock.mockReset();
  writeTextMock.mockReset().mockResolvedValue(undefined);
  openMock.mockReset();

  // jsdom's navigator.clipboard is read-only in some versions — define via
  // Object.defineProperty so subsequent tests can swap it out.
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

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('CrashPreviewDialog — initial fetch & layout', () => {
  it('calls crashApi.getPrefillUrl(crash.id) once on mount', async () => {
    const crash = makeCrash({ id: 'c'.repeat(32) });
    render(CrashPreviewDialog, {
      crash,
      onClose: vi.fn(),
    });
    await waitFor(() => expect(getPrefillUrlMock).toHaveBeenCalledTimes(1));
    expect(getPrefillUrlMock).toHaveBeenCalledWith('c'.repeat(32));
  });

  it('seeds title input, body textarea, and label chips from the URL', async () => {
    renderDialog();
    const titleInput = (await screen.findByLabelText('タイトル')) as HTMLInputElement;
    expect(titleInput.value).toBe(DEFAULT_TITLE);
    const bodyTextarea = (await screen.findByLabelText('本文')) as HTMLTextAreaElement;
    expect(bodyTextarea.value).toBe(DEFAULT_BODY);
    for (const label of DEFAULT_LABELS) {
      expect(screen.getByText(label)).toBeTruthy();
    }
  });

  it('renders the 3 footer buttons (却下 / コピー / GitHubで開く →)', async () => {
    renderDialog();
    expect(await screen.findByRole('button', { name: '却下' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'クリップボードにコピー' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'GitHubで開く →' })).toBeTruthy();
  });

  it('shows truncation warning when the backend reports truncated=true', async () => {
    getPrefillUrlMock.mockResolvedValueOnce(defaultPrefillResponse({ truncated: true }));
    renderDialog();
    await waitFor(() => {
      expect(screen.getByText(/切り詰め|truncat/i)).toBeTruthy();
    });
  });

  it('does NOT show truncation warning when truncated=false', async () => {
    renderDialog();
    await screen.findByLabelText('タイトル');
    expect(screen.queryByText(/切り詰め|truncat/i)).toBeNull();
  });

  it('parses missing labels= query param as empty list (no phantom "" chip)', async () => {
    getPrefillUrlMock.mockResolvedValueOnce({
      // No labels= at all.
      url: 'https://github.com/KawanoMomo/notebook-ollama/issues/new?title=x&body=y',
      truncated: false,
    });
    const { container } = renderDialog();
    await screen.findByLabelText('タイトル');
    // A "" chip would have empty text content — easy to detect because the
    // remove button next to it would carry an empty aria-label.
    const chips = container.querySelectorAll('[data-role="label-chip"]');
    expect(chips.length).toBe(0);
  });

  it('renders nothing-fatal when getPrefillUrl rejects, surfaces an error', async () => {
    getPrefillUrlMock.mockRejectedValueOnce(new Error('500'));
    renderDialog();
    await waitFor(() => {
      // Some user-facing error (don't pin exact copy, just CJK error label).
      expect(screen.getByText(/読み込み|失敗|エラー/)).toBeTruthy();
    });
    // Form did not render.
    expect(screen.queryByLabelText('タイトル')).toBeNull();
  });
});

describe('CrashPreviewDialog — editing', () => {
  it('updates state when the user edits the title', async () => {
    renderDialog();
    const titleInput = (await screen.findByLabelText('タイトル')) as HTMLInputElement;
    await fireEvent.input(titleInput, { target: { value: '[crash] 編集後のタイトル 💥' } });
    expect(titleInput.value).toBe('[crash] 編集後のタイトル 💥');
  });

  it('updates state when the user edits the body', async () => {
    renderDialog();
    const body = (await screen.findByLabelText('本文')) as HTMLTextAreaElement;
    await fireEvent.input(body, { target: { value: '## 新しい本文\n再現手順:\n1. クリック' } });
    expect(body.value).toBe('## 新しい本文\n再現手順:\n1. クリック');
  });

  it('adds a new label chip via the add-label input', async () => {
    renderDialog();
    await screen.findByLabelText('タイトル');
    const labelInput = screen.getByLabelText('ラベル追加') as HTMLInputElement;
    await fireEvent.input(labelInput, { target: { value: 'investigated' } });
    await fireEvent.keyDown(labelInput, { key: 'Enter' });
    expect(screen.getByText('investigated')).toBeTruthy();
    // input is cleared after add
    expect(labelInput.value).toBe('');
  });

  it('refuses to add an empty / whitespace-only label', async () => {
    const { container } = renderDialog();
    await screen.findByLabelText('タイトル');
    const labelInput = screen.getByLabelText('ラベル追加') as HTMLInputElement;
    const before = container.querySelectorAll('[data-role="label-chip"]').length;
    await fireEvent.input(labelInput, { target: { value: '   ' } });
    await fireEvent.keyDown(labelInput, { key: 'Enter' });
    const after = container.querySelectorAll('[data-role="label-chip"]').length;
    expect(after).toBe(before);
  });

  it('does not duplicate an existing label (idempotent add)', async () => {
    const { container } = renderDialog();
    await screen.findByLabelText('タイトル');
    const labelInput = screen.getByLabelText('ラベル追加') as HTMLInputElement;
    const before = container.querySelectorAll('[data-role="label-chip"]').length;
    await fireEvent.input(labelInput, { target: { value: 'crash-auto' } });
    await fireEvent.keyDown(labelInput, { key: 'Enter' });
    const after = container.querySelectorAll('[data-role="label-chip"]').length;
    expect(after).toBe(before);
  });

  it('removes a label chip via its remove button', async () => {
    renderDialog();
    await screen.findByLabelText('タイトル');
    expect(screen.getByText('crash-auto')).toBeTruthy();
    const removeBtn = screen.getByLabelText('ラベル削除: crash-auto');
    await fireEvent.click(removeBtn);
    expect(screen.queryByText('crash-auto')).toBeNull();
    // The other label is still there.
    expect(screen.getByText('needs-triage')).toBeTruthy();
  });
});

describe('CrashPreviewDialog — 却下 (dismiss)', () => {
  it('calls crashApi.dismiss(id) then onDismissed and onClose', async () => {
    const { onClose, onDismissed } = renderDialog();
    await screen.findByLabelText('タイトル');

    await fireEvent.click(screen.getByRole('button', { name: '却下' }));
    await waitFor(() => expect(dismissMock).toHaveBeenCalledTimes(1));

    expect(dismissMock).toHaveBeenCalledWith('a'.repeat(32));
    expect(onDismissed).toHaveBeenCalledWith('a'.repeat(32));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('keeps the dialog open if dismiss rejects (user can retry)', async () => {
    dismissMock.mockRejectedValueOnce(new Error('disk full'));
    const { onClose, onDismissed } = renderDialog();
    await screen.findByLabelText('タイトル');

    await fireEvent.click(screen.getByRole('button', { name: '却下' }));
    await waitFor(() => expect(dismissMock).toHaveBeenCalledTimes(1));

    expect(onDismissed).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    // user-facing error
    await waitFor(() => expect(pushToastMock).toHaveBeenCalled());
  });
});

describe('CrashPreviewDialog — クリップボードにコピー', () => {
  it('writes the *current* (edited) body to the clipboard and shows a success toast', async () => {
    renderDialog();
    const body = (await screen.findByLabelText('本文')) as HTMLTextAreaElement;
    await fireEvent.input(body, { target: { value: '編集後の本文 💥' } });
    await fireEvent.click(screen.getByRole('button', { name: 'クリップボードにコピー' }));

    await waitFor(() => expect(writeTextMock).toHaveBeenCalledWith('編集後の本文 💥'));
    expect(pushToastMock).toHaveBeenCalledWith(expect.any(String), 'success');
  });

  it('surfaces an error toast (does not throw) if clipboard.writeText rejects', async () => {
    writeTextMock.mockRejectedValueOnce(new Error('permission denied'));
    renderDialog();
    await screen.findByLabelText('本文');
    await fireEvent.click(screen.getByRole('button', { name: 'クリップボードにコピー' }));
    await waitFor(() => {
      expect(pushToastMock).toHaveBeenCalledWith(expect.any(String), 'error');
    });
  });
});

describe('CrashPreviewDialog — GitHubで開く →', () => {
  it('rebuilds URL with edited title/body/labels then opens it in a new tab', async () => {
    const { onClose, onReported } = renderDialog();
    const title = (await screen.findByLabelText('タイトル')) as HTMLInputElement;
    const body = (await screen.findByLabelText('本文')) as HTMLTextAreaElement;

    await fireEvent.input(title, { target: { value: '[crash] 編集後 💥' } });
    await fireEvent.input(body, { target: { value: '編集後 本文' } });

    // Remove a label to prove labels are read from current state, not the fetch.
    await fireEvent.click(screen.getByLabelText('ラベル削除: needs-triage'));

    await fireEvent.click(screen.getByRole('button', { name: 'GitHubで開く →' }));

    await waitFor(() => expect(openMock).toHaveBeenCalledTimes(1));
    const [openUrl, target] = openMock.mock.calls[0] as [string, string];
    expect(target).toBe('_blank');

    const u = new URL(openUrl);
    expect(u.origin + u.pathname).toBe(
      'https://github.com/KawanoMomo/notebook-ollama/issues/new',
    );
    expect(u.searchParams.get('title')).toBe('[crash] 編集後 💥');
    expect(u.searchParams.get('body')).toBe('編集後 本文');
    expect(u.searchParams.get('labels')).toBe('crash-auto');

    await waitFor(() => expect(markReportedMock).toHaveBeenCalledWith('a'.repeat(32)));
    expect(onReported).toHaveBeenCalledWith('a'.repeat(32));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('round-trips unicode CJK + emoji through parse → edit → rebuild', async () => {
    // Seed the URL with CJK + emoji content so the parse step is exercised
    // by the same characters that come back out via rebuild.
    getPrefillUrlMock.mockResolvedValueOnce(
      defaultPrefillResponse({
        title: '[crash] 致命的なエラー 💥',
        body: '## 概要\n致命的なエラー 💥',
        labels: ['crash-auto', '日本語ラベル'],
      }),
    );
    renderDialog();
    const title = (await screen.findByLabelText('タイトル')) as HTMLInputElement;
    expect(title.value).toBe('[crash] 致命的なエラー 💥');

    await fireEvent.click(screen.getByRole('button', { name: 'GitHubで開く →' }));
    await waitFor(() => expect(openMock).toHaveBeenCalledTimes(1));
    const u = new URL(openMock.mock.calls[0][0] as string);
    expect(u.searchParams.get('title')).toBe('[crash] 致命的なエラー 💥');
    expect(u.searchParams.get('body')).toBe('## 概要\n致命的なエラー 💥');
    expect(u.searchParams.get('labels')).toBe('crash-auto,日本語ラベル');
  });

  it('keeps the dialog open if markReported rejects (window already opened)', async () => {
    markReportedMock.mockRejectedValueOnce(new Error('500'));
    const { onClose, onReported } = renderDialog();
    await screen.findByLabelText('タイトル');

    await fireEvent.click(screen.getByRole('button', { name: 'GitHubで開く →' }));
    // window.open still happens — the URL is what the user wants regardless
    // of whether we successfully marked the crash as reported.
    await waitFor(() => expect(openMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(markReportedMock).toHaveBeenCalledTimes(1));

    expect(onReported).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    await waitFor(() => expect(pushToastMock).toHaveBeenCalledWith(expect.any(String), 'error'));
  });
});

describe('CrashPreviewDialog — Escape closes', () => {
  it('closes when Escape is pressed', async () => {
    const { onClose } = renderDialog();
    await screen.findByLabelText('タイトル');
    await fireEvent.keyDown(window, { key: 'Escape' });
    await tick();
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

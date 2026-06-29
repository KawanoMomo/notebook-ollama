/**
 * E2E coverage for the クラッシュレポート & フィードバックハブ feature.
 *
 * spec: docs/specs/2026-06-28-crash-report-feedback-hub-design.md §11.3
 * plan: docs/superpowers/plans/2026-06-28-crash-report-feedback-hub.md Task 9.1
 *
 * Five scenarios verify the user-visible flow end-to-end against the real
 * uvicorn backend on :8765 (vite proxies /api).
 *
 *   S1 — synthetic FE error → CrashDetectionModal → CrashPreviewDialog →
 *        「GitHubで開く」 → window.open URL matches the configured repo.
 *   S2 — header Megaphone opens the right drawer; tabs お知らせ / 不具合 /
 *        ご意見 swap aria-selected.
 *   S3 — clicking a notice persists 既読 to localStorage and removes the
 *        unread dot (and survives a reload).
 *   S4 — `auto_prompt=false` suppresses the modal even when a crash fires,
 *        but the row still lands in the backend pending list.
 *   S5 — a forged unclean-shutdown PendingCrash on disk surfaces in the
 *        不具合 tab when the FE refreshes the store.
 *
 * Implementation choices that matter:
 *
 * - `window.open` is intercepted via `page.addInitScript` (not by waiting
 *   for a real popup). Spec §11.3 explicitly notes "Issue 起票自体はモック".
 *   Capturing the URL string is sufficient and avoids flakiness from real
 *   github.com hits during local runs.
 *
 * - Synthetic errors are dispatched via `window.dispatchEvent(new ErrorEvent
 *   (...))` so the errorBoundary listener fires the same code path it would
 *   in production. We use a unique message per dispatch to dodge the boundary's
 *   5-second same-message throttle.
 *
 * - S5 forges the PendingCrash JSON directly under `~/.notebook-ollama/crash-
 *   pending/` rather than restarting the backend to exercise `lifecycle.acquire`.
 *   Restarting uvicorn mid-Playwright-run is non-trivial; the integration test
 *   suite (`tests/integration/crash_reporter/test_lifecycle.py`) already covers
 *   the acquire path. This E2E asserts the user-visible behaviour: the row
 *   shows up in the 不具合 tab with the forged exception_message.
 *
 * - Each test resets `crash_report` to a known opted-in state in `beforeEach`
 *   via PUT /api/settings/crash-report so they don't depend on whatever the
 *   developer left toggled in the live config.
 */
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { promises as fs } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

// Backend URL — vite proxies /api but the test layer talks to uvicorn directly
// via the `request` fixture so PUT /api/settings/crash-report and POST /report
// don't depend on a hydrated frontend.
//
// IPv4 literal (not "localhost") is intentional: uvicorn binds 127.0.0.1 by
// default (see core.config.ServerSettings) and Node's getaddrinfo prefers
// `::1` on Windows, which yields ECONNREFUSED against an IPv4-only listener.
const API_BASE = 'http://127.0.0.1:8765';

// Mirror of `core.config._default_data_dir()` (~/.notebook-ollama). Forging
// PendingCrash JSON here is the closest E2E substitute for the unclean-shutdown
// path that doesn't require restarting uvicorn.
const DATA_DIR = join(homedir(), '.notebook-ollama');
const CRASH_PENDING_DIR = join(DATA_DIR, 'crash-pending');

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function setCrashReportSettings(
  request: APIRequestContext,
  opts: { enabled: boolean; auto_prompt: boolean },
): Promise<void> {
  const res = await request.put(`${API_BASE}/api/settings/crash-report`, {
    data: {
      enabled: opts.enabled,
      auto_prompt: opts.auto_prompt,
      // Re-stamp opted_in_at on every test so the FE never sees a stale null
      // that would re-trigger OptInDialog mid-test.
      opted_in_at: new Date().toISOString(),
    },
  });
  if (!res.ok()) {
    throw new Error(
      `PUT /api/settings/crash-report failed: ${res.status()} ${await res.text()}`,
    );
  }
}

/**
 * Navigate to `/` and wait until the layout-driven GET /api/settings has
 * resolved. The errorBoundary's settings gate short-circuits while
 * `settings === null`, so synthetic errors dispatched too early are silently
 * dropped. Awaiting the response (set up BEFORE goto so the listener catches
 * the in-flight request) prevents that race.
 */
async function gotoHomeWithSettings(page: Page): Promise<void> {
  const settingsP = page.waitForResponse(
    (r) =>
      r.url().includes('/api/settings') &&
      r.request().method() === 'GET' &&
      r.status() === 200,
    { timeout: 15_000 },
  );
  await page.goto('/');
  await settingsP;
  // Give Svelte's microtasks a chance to propagate the loaded settings into
  // the boundary's derived `crashReport` accessor before the test dispatches.
  await page.waitForLoadState('networkidle');
}

async function dispatchSyntheticError(page: Page, message: string): Promise<void> {
  await page.evaluate((msg) => {
    const err = new Error(msg);
    const ev = new ErrorEvent('error', {
      error: err,
      message: msg,
      filename: 'synthetic.js',
      lineno: 1,
      colno: 1,
    });
    window.dispatchEvent(ev);
  }, message);
}

/**
 * Install a window.open shim on every page in the context that records the
 * URL into `window.__lastOpenedUrl`. Returns the page-side reader.
 */
async function installWindowOpenSpy(page: Page): Promise<() => Promise<string | null>> {
  await page.addInitScript(() => {
    (window as unknown as { __lastOpenedUrl: string | null }).__lastOpenedUrl = null;
    const orig = window.open;
    // Preserve the original so any UI that genuinely needs a popup (none
    // expected in this suite) can fall back via `__origOpen`.
    (window as unknown as { __origOpen: typeof window.open }).__origOpen = orig;
    window.open = (url?: string | URL): null => {
      (window as unknown as { __lastOpenedUrl: string | null }).__lastOpenedUrl =
        url != null ? String(url) : null;
      return null;
    };
  });
  return () =>
    page.evaluate(
      () => (window as unknown as { __lastOpenedUrl: string | null }).__lastOpenedUrl,
    );
}

/**
 * Write a PendingCrash JSON straight to disk. The backend re-scans
 * `crash-pending/*.json` on every GET /api/crash/pending, so the next
 * frontend refresh picks it up without a uvicorn restart.
 */
async function forgeUncleanShutdownPending(
  id: string,
  message: string,
): Promise<string> {
  await fs.mkdir(CRASH_PENDING_DIR, { recursive: true });
  const path = join(CRASH_PENDING_DIR, `${id}.json`);
  const payload = {
    id,
    fingerprint: `forged-${id}`,
    created_at: new Date().toISOString().replace(/\.\d+Z$/, 'Z'),
    exception_type: 'UncleanShutdown',
    exception_message: message,
    trace: [],
    hardware: {},
    log_tail: [
      {
        level: 'ERROR',
        event_name: 'app.crash',
        timestamp: new Date().toISOString().replace(/\.\d+Z$/, 'Z'),
        exception_type: 'UncleanShutdown',
        exception_module: 'tests.e2e.feedback_hub',
      },
    ],
    source: 'unclean_shutdown',
  };
  await fs.writeFile(path, JSON.stringify(payload, null, 2), 'utf-8');
  return path;
}

async function safeUnlink(path: string): Promise<void> {
  try {
    await fs.unlink(path);
  } catch {
    // Best-effort cleanup; the next test's beforeAll/afterAll picks up the slack.
  }
}

async function dismissByMessage(
  request: APIRequestContext,
  message: string,
): Promise<void> {
  const r = await request.get(`${API_BASE}/api/crash/pending`);
  if (!r.ok()) return;
  const pending = (await r.json()) as Array<{ id: string; exception_message: string }>;
  for (const c of pending) {
    if (c.exception_message === message) {
      await request.post(`${API_BASE}/api/crash/${c.id}/dismiss`);
    }
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('feedback hub & crash report (spec §11.3)', () => {
  test.beforeEach(async ({ request }) => {
    // Default state: fully opted in. Scenario 4 overrides this with
    // auto_prompt=false; all others rely on this default.
    await setCrashReportSettings(request, { enabled: true, auto_prompt: true });
  });

  // -------------------------------------------------------------------------
  // S1 — synthetic FE error → modal → preview → GitHub open
  // -------------------------------------------------------------------------
  test('S1: synthetic error → CrashDetectionModal → CrashPreviewDialog → window.open(github)', async ({
    page,
    request,
  }) => {
    const readOpenedUrl = await installWindowOpenSpy(page);
    await gotoHomeWithSettings(page);

    const uniqMsg = `S1-synthetic-${Date.now()}`;

    try {
      await dispatchSyntheticError(page, uniqMsg);

      // alertdialog mounts after POST /api/crash/report resolves and the
      // store's showImmediate fires.
      const dialog = page.getByRole('alertdialog');
      await expect(dialog).toBeVisible({ timeout: 10_000 });
      await expect(dialog).toContainText('エラーが発生しました');
      await expect(dialog.locator('[data-testid="crash-summary"]')).toContainText(
        uniqMsg,
      );

      await dialog.getByRole('button', { name: /送信内容をプレビュー/ }).click();

      // CrashPreviewDialog mounts; its dialog has aria-label="クラッシュレポートのプレビュー".
      const preview = page.getByRole('dialog', { name: 'クラッシュレポートのプレビュー' });
      await expect(preview).toBeVisible({ timeout: 10_000 });

      // Editable form fields are present and accessible.
      await expect(preview.getByLabel('タイトル')).toBeVisible();
      await expect(preview.getByLabel('本文')).toBeVisible();

      // GitHub-open button is disabled until prefill-url GET resolves; rely on
      // its enabled state as the load-complete signal.
      const openBtn = preview.getByRole('button', { name: /GitHubで開く/ });
      await expect(openBtn).toBeEnabled({ timeout: 10_000 });
      await openBtn.click();

      // The stubbed window.open should now have captured a URL aimed at the
      // configured repo (KawanoMomo/notebook-ollama).
      await expect
        .poll(readOpenedUrl, { timeout: 5_000 })
        .toMatch(/^https:\/\/github\.com\/KawanoMomo\/notebook-ollama\/issues\/new/);
    } finally {
      // markReported is fire-after-open; either way scrub any straggler entry
      // matching our unique message so re-runs stay clean.
      await dismissByMessage(request, uniqMsg);
    }
  });

  // -------------------------------------------------------------------------
  // S2 — Megaphone opens drawer, tabs switch aria-selected
  // -------------------------------------------------------------------------
  test('S2: header Megaphone opens drawer; お知らせ/不具合/ご意見 tabs swap aria-selected', async ({
    page,
  }) => {
    await gotoHomeWithSettings(page);

    await page.getByRole('button', { name: 'お知らせ・フィードバック' }).first().click();

    const drawer = page.getByRole('dialog', { name: 'お知らせ・フィードバック' });
    await expect(drawer).toBeVisible();

    const noticesTab = drawer.getByRole('tab', { name: /お知らせ/ });
    const bugsTab = drawer.getByRole('tab', { name: /不具合/ });
    const feedbackTab = drawer.getByRole('tab', { name: /ご意見/ });

    // notices is the default active tab (spec §5.2).
    await expect(noticesTab).toHaveAttribute('aria-selected', 'true');
    await expect(bugsTab).toHaveAttribute('aria-selected', 'false');
    await expect(feedbackTab).toHaveAttribute('aria-selected', 'false');

    await bugsTab.click();
    await expect(bugsTab).toHaveAttribute('aria-selected', 'true');
    await expect(noticesTab).toHaveAttribute('aria-selected', 'false');

    await feedbackTab.click();
    await expect(feedbackTab).toHaveAttribute('aria-selected', 'true');
    await expect(bugsTab).toHaveAttribute('aria-selected', 'false');

    await noticesTab.click();
    await expect(noticesTab).toHaveAttribute('aria-selected', 'true');
    await expect(feedbackTab).toHaveAttribute('aria-selected', 'false');
  });

  // -------------------------------------------------------------------------
  // S3 — notice click persists 既読 to localStorage and survives reload
  // -------------------------------------------------------------------------
  test('S3: clicking a notice updates localStorage and removes the unread dot', async ({
    page,
  }) => {
    await gotoHomeWithSettings(page);

    await page.getByRole('button', { name: 'お知らせ・フィードバック' }).first().click();

    const drawer = page.getByRole('dialog', { name: 'お知らせ・フィードバック' });
    await expect(drawer).toBeVisible();

    // The notices list is loaded async; wait for at least one entry before we
    // try to click it. If notices.json is empty in this checkout, we skip
    // gracefully — the scenario only makes sense when there's data to read.
    const firstEntry = drawer.locator('article.entry').first();
    try {
      await expect(firstEntry).toBeVisible({ timeout: 10_000 });
    } catch {
      test.skip(true, 'No notices in data/notices.json — nothing to mark as read');
      return;
    }

    // Capture the notice id (the title text suffices as a stable handle since
    // article elements don't expose id directly). We re-find by text post-reload.
    const entryTitle = await firstEntry.locator('.entry-title').innerText();

    await expect(firstEntry).toHaveClass(/unread/);

    await firstEntry.click();

    await expect(firstEntry).not.toHaveClass(/unread/);

    // localStorage now records at least one seen id.
    const seen = await page.evaluate(() => {
      const raw = localStorage.getItem('seen_notice_ids');
      return raw ? (JSON.parse(raw) as unknown) : null;
    });
    expect(Array.isArray(seen)).toBe(true);
    expect((seen as string[]).length).toBeGreaterThan(0);

    // Reload: localStorage persists, so the entry stays read.
    const settingsP = page.waitForResponse(
      (r) =>
        r.url().includes('/api/settings') &&
        r.request().method() === 'GET' &&
        r.status() === 200,
      { timeout: 15_000 },
    );
    await page.reload();
    await settingsP;
    await page.waitForLoadState('networkidle');

    await page.getByRole('button', { name: 'お知らせ・フィードバック' }).first().click();
    const drawer2 = page.getByRole('dialog', { name: 'お知らせ・フィードバック' });
    await expect(drawer2).toBeVisible();

    // Re-locate the same entry by its title text (id-stable across reload).
    const sameEntry = drawer2
      .locator('article.entry', { hasText: entryTitle })
      .first();
    await expect(sameEntry).toBeVisible({ timeout: 10_000 });
    await expect(sameEntry).not.toHaveClass(/unread/);
  });

  // -------------------------------------------------------------------------
  // S4 — auto_prompt=false suppresses the modal but records the crash
  // -------------------------------------------------------------------------
  test('S4: auto_prompt=false suppresses CrashDetectionModal but POST still lands', async ({
    page,
    request,
  }) => {
    // Override the beforeEach: opted in but no auto popup.
    await setCrashReportSettings(request, { enabled: true, auto_prompt: false });

    await gotoHomeWithSettings(page);

    const uniqMsg = `S4-suppressed-${Date.now()}`;
    try {
      await dispatchSyntheticError(page, uniqMsg);

      // No alertdialog should appear within 3s. We wait the full window
      // (rather than asserting `.not.toBeVisible()` immediately) because
      // showImmediate is gated by the auto_prompt re-read which happens
      // after the POST resolves — a too-eager negative assertion could
      // false-pass before the gate ran.
      await page.waitForTimeout(3_000);
      await expect(page.getByRole('alertdialog')).toHaveCount(0);

      // The crash row still lands in the backend pending list so the user
      // can review it later from the 不具合 tab (spec §7.3 collect-but-don't-popup).
      const listResp = await request.get(`${API_BASE}/api/crash/pending`);
      expect(listResp.ok()).toBe(true);
      const pending = (await listResp.json()) as Array<{
        id: string;
        exception_message: string;
      }>;
      const ours = pending.find((p) => p.exception_message === uniqMsg);
      expect(ours, 'crash row should be persisted even when auto_prompt is off').toBeTruthy();
    } finally {
      await dismissByMessage(request, uniqMsg);
      // Restore the default in case any subsequent test relies on it
      // (defense-in-depth — beforeEach already does this).
      await setCrashReportSettings(request, { enabled: true, auto_prompt: true });
    }
  });

  // -------------------------------------------------------------------------
  // S5 — forged unclean-shutdown PendingCrash surfaces in 不具合 tab
  // -------------------------------------------------------------------------
  test('S5: forged unclean-shutdown pending row appears in 不具合 tab', async ({
    page,
    request,
  }) => {
    // See module docstring: full lifecycle.acquire is covered by integration
    // tests; this E2E asserts the UI surfaces the row once it exists on disk.
    const uniqMsg = `S5-unclean-${Date.now()}`;
    const forgedId = `e2e-unclean-${Date.now()}`;
    const forgedPath = await forgeUncleanShutdownPending(forgedId, uniqMsg);

    try {
      await gotoHomeWithSettings(page);

      await page.getByRole('button', { name: 'お知らせ・フィードバック' }).first().click();
      const drawer = page.getByRole('dialog', { name: 'お知らせ・フィードバック' });
      await expect(drawer).toBeVisible();

      await drawer.getByRole('tab', { name: /不具合/ }).click();

      // The BugReportTab renders exception_message; it triggers an API load on
      // mount if the store hasn't been populated yet, so our forged row should
      // be visible after at most one round-trip.
      const row = drawer.locator('[data-testid="crash-row"]', { hasText: uniqMsg });
      await expect(row).toBeVisible({ timeout: 10_000 });
      await expect(row).toContainText('UncleanShutdown');
    } finally {
      // Tear down the forged file. The pending list will then drop it on the
      // next /api/crash/pending call.
      await safeUnlink(forgedPath);
    }
  });
});

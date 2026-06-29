/**
 * screenshotCapture tests (Sprint 8 Task 8.2).
 *
 * `screenshotCapture.ts` wraps `html2canvas` and exposes four flavours of
 * "current view → PNG" for the FeedbackHub flow (spec §8.3):
 *
 *   - captureCurrentView()         → Blob (image/png)
 *   - captureToBase64()            → 'data:image/png;base64,…' data URL
 *   - captureToBase64Stripped()    → bare base64 body (no data URL prefix)
 *   - captureCurrentViewAsFile()   → File ('screenshot.png', image/png)
 *
 * html2canvas touches real DOM + canvas APIs at runtime; jsdom does NOT
 * implement <canvas>.getContext('2d') / toBlob meaningfully. We therefore
 * mock `html2canvas` at the import level — every test runs against a
 * synthetic canvas whose `toBlob` callback we control.
 *
 * Coverage checklist:
 *   - happy path: Blob round-trips through every wrapper.
 *   - options passthrough: backgroundColor / scale / logging / ignoreElements
 *     reach html2canvas exactly as specced.
 *   - ignoreElements callback: returns true for `.no-screenshot`, false otherwise
 *     (this is the seam that prevents the FeedbackHub drawer from being
 *     captured into the user's own screenshot — see plan §8.2 Step 1).
 *   - Error path: html2canvas rejects → captureCurrentView re-throws (NO
 *     silent swallow — a corrupted screenshot must surface to the caller so
 *     they can show an error toast instead of attaching empty bytes).
 *   - Edge: canvas.toBlob calls back with null → rejects with a descriptive
 *     error (browsers do this when the canvas is tainted by cross-origin
 *     content; we must not resolve with `null` cast as Blob).
 *   - captureToBase64 returns a data URL string (prefix preserved).
 *   - captureToBase64Stripped strips the 'data:image/png;base64,' prefix
 *     (server-side payloads typically want the bare body).
 *   - captureCurrentViewAsFile returns a File with the requested name and
 *     image/png MIME, default 'screenshot.png'.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Mock html2canvas at the module level. The factory MUST be a function (vi
// hoists it above the import), and it MUST return an object with `default`
// because `screenshotCapture.ts` imports the default export.
//
// We can't reference `mockHtml2Canvas` directly inside the factory (vitest
// hoists vi.mock above any module-scope let/const, so the binding doesn't
// exist yet). Instead the factory installs a getter that the test setup
// reassigns per-test via `mockHtml2Canvas.mockImplementation(...)`.
const mockHtml2Canvas = vi.fn();
const mockToBlob = vi.fn();

vi.mock('html2canvas', () => ({
  __esModule: true,
  default: (...args: unknown[]) => mockHtml2Canvas(...args),
}));

// Import AFTER vi.mock so screenshotCapture sees the mock binding.
// eslint-disable-next-line import/first
import {
  captureCurrentView,
  captureToBase64,
  captureToBase64Stripped,
  captureCurrentViewAsFile,
} from '$lib/utils/screenshotCapture';
// Raw-source import (Vite `?raw`): assert FeedbackHubDrawer's root carries
// `class="no-screenshot"` so that the `ignoreElements` callback above actually
// excludes the drawer from the captured screenshot. Using the raw source
// (same trick FeedbackHubDrawer.test.ts uses for its `transition:fly` guard)
// avoids importing the drawer's full store/API graph into a utils test.
// eslint-disable-next-line import/first
import drawerSource from '$lib/components/FeedbackHubDrawer.svelte?raw';

/** Synthetic PNG-ish blob used by the default mock toBlob path. */
function makeMockPngBlob(content = 'PNG_BYTES'): Blob {
  return new Blob([content], { type: 'image/png' });
}

beforeEach(() => {
  mockHtml2Canvas.mockReset();
  mockToBlob.mockReset();
  // Happy default: html2canvas resolves with a mock canvas whose toBlob
  // immediately calls back with a real (jsdom) Blob of type image/png.
  mockHtml2Canvas.mockResolvedValue({ toBlob: mockToBlob });
  mockToBlob.mockImplementation(
    (cb: (b: Blob | null) => void, _type?: string) => cb(makeMockPngBlob()),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('captureCurrentView — happy path', () => {
  it('returns a Blob produced via the mocked canvas.toBlob', async () => {
    const blob = await captureCurrentView();
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.type).toBe('image/png');
    // The mock returned a non-empty blob.
    expect(blob.size).toBeGreaterThan(0);
  });

  it('calls html2canvas exactly once against document.body', async () => {
    await captureCurrentView();
    expect(mockHtml2Canvas).toHaveBeenCalledTimes(1);
    const target = mockHtml2Canvas.mock.calls[0][0];
    expect(target).toBe(document.body);
  });

  it('passes the specced options (backgroundColor / scale / logging) to html2canvas', async () => {
    await captureCurrentView();
    const opts = mockHtml2Canvas.mock.calls[0][1] as Record<string, unknown>;
    expect(opts).toMatchObject({
      backgroundColor: '#ffffff',
      scale: 1,
      logging: false,
    });
    expect(typeof opts.ignoreElements).toBe('function');
  });

  it('requests the image/png mime from canvas.toBlob', async () => {
    await captureCurrentView();
    expect(mockToBlob).toHaveBeenCalledTimes(1);
    // 2nd arg is the mime; toBlob defaults to image/png if omitted, but the
    // spec is explicit so we assert it's wired through.
    expect(mockToBlob.mock.calls[0][1]).toBe('image/png');
  });
});

describe('captureCurrentView — ignoreElements callback (drawer-self-screenshot guard)', () => {
  it('returns true for elements carrying the .no-screenshot class', async () => {
    await captureCurrentView();
    const ignoreFn = mockHtml2Canvas.mock.calls[0][1].ignoreElements as (
      el: Element,
    ) => boolean;
    const hidden = document.createElement('div');
    hidden.className = 'no-screenshot';
    expect(ignoreFn(hidden)).toBe(true);
  });

  it('returns false for elements without the .no-screenshot class', async () => {
    await captureCurrentView();
    const ignoreFn = mockHtml2Canvas.mock.calls[0][1].ignoreElements as (
      el: Element,
    ) => boolean;
    const visible = document.createElement('section');
    visible.className = 'panel main-content';
    expect(ignoreFn(visible)).toBe(false);
    // Bare element with no classes at all.
    expect(ignoreFn(document.createElement('span'))).toBe(false);
  });

  it('returns true when .no-screenshot is one of several classes', async () => {
    await captureCurrentView();
    const ignoreFn = mockHtml2Canvas.mock.calls[0][1].ignoreElements as (
      el: Element,
    ) => boolean;
    const drawer = document.createElement('aside');
    drawer.className = 'feedback-hub-drawer no-screenshot open';
    expect(ignoreFn(drawer)).toBe(true);
  });
});

describe('captureCurrentView — error paths', () => {
  it('re-throws when html2canvas itself rejects (no silent swallow)', async () => {
    mockHtml2Canvas.mockRejectedValueOnce(new Error('canvas tainted by cross-origin image'));
    await expect(captureCurrentView()).rejects.toThrow('canvas tainted by cross-origin image');
  });

  it('rejects with a descriptive error when canvas.toBlob produces null', async () => {
    // Real browsers hand back null when the canvas is tainted. We MUST NOT
    // resolve as if everything were fine — downstream would attach an empty
    // blob to the issue.
    mockToBlob.mockImplementationOnce(
      (cb: (b: Blob | null) => void) => cb(null),
    );
    await expect(captureCurrentView()).rejects.toThrow(/null|empty|toBlob/i);
  });

  it('rejects when canvas.toBlob produces a 0-byte Blob (empty PNG)', async () => {
    // Spec header §"Error policy" promises: "empty bytes must surface as a
    // rejection". `null` is one such case; a `Blob` with `size === 0` is
    // another (browsers can hand back an empty PNG when the canvas is
    // logically valid but contains no drawn pixels — e.g. a torn-down DOM
    // by the time toBlob fires). Attaching an empty PNG to a GitHub Issue
    // is worse than no screenshot at all: it looks like a successful
    // capture to the user but carries zero diagnostic value.
    mockToBlob.mockImplementationOnce((cb: (b: Blob | null) => void) =>
      cb(new Blob([], { type: 'image/png' })),
    );
    await expect(captureCurrentView()).rejects.toThrow(/empty/i);
  });
});

describe('FeedbackHubDrawer — drawer-self-screenshot guard wiring', () => {
  // Source-level regression guard. The actual exclusion behaviour at runtime
  // is owned by html2canvas + the `ignoreElements` callback (covered above);
  // here we only confirm the wiring on the drawer side is intact, since the
  // callback fires on zero elements otherwise.
  //
  // plan §8.2 Step 1 / spec §8.3: the drawer's root MUST carry the
  // `no-screenshot` marker class so the ignoreElements callback can find it.
  it('FeedbackHubDrawer.svelte has class="no-screenshot" on the .drawer root', () => {
    // Match a class attribute on a tag whose `class=` contains BOTH `drawer`
    // and `no-screenshot` (order-agnostic). Allow either single or double
    // quotes and any other classes in between.
    const hasDrawerWithMarker =
      /class\s*=\s*["'][^"']*\bdrawer\b[^"']*\bno-screenshot\b[^"']*["']/.test(
        drawerSource,
      ) ||
      /class\s*=\s*["'][^"']*\bno-screenshot\b[^"']*\bdrawer\b[^"']*["']/.test(
        drawerSource,
      );
    expect(hasDrawerWithMarker).toBe(true);
  });

  // Documentation test for cascading behaviour: html2canvas itself skips the
  // subtree once `ignoreElements` returns true for an ancestor, so we do NOT
  // need to walk descendants in our callback — checking only `el.classList`
  // is sufficient. The callback returning true for the .drawer root is enough
  // to exclude every tab/button/input inside it from the captured PNG.
  it('ignoreElements need not match descendants — html2canvas prunes the subtree of the first match', async () => {
    await captureCurrentView();
    const ignoreFn = mockHtml2Canvas.mock.calls[0][1].ignoreElements as (
      el: Element,
    ) => boolean;
    // A descendant of a `.no-screenshot` element that itself does NOT carry
    // the class is correctly reported as "not ignorable" by our callback.
    // (html2canvas will never invoke the callback on it anyway, because the
    // parent already returned true; this test documents the contract.)
    const innerButton = document.createElement('button');
    innerButton.className = 'tab active';
    expect(ignoreFn(innerButton)).toBe(false);
  });
});

describe('captureToBase64', () => {
  it('returns a data URL string with the image/png prefix', async () => {
    const dataUrl = await captureToBase64();
    expect(typeof dataUrl).toBe('string');
    expect(dataUrl.startsWith('data:image/png;base64,')).toBe(true);
    // and contains a non-empty base64 body
    expect(dataUrl.length).toBeGreaterThan('data:image/png;base64,'.length);
  });
});

describe('captureToBase64Stripped', () => {
  it('strips the "data:image/png;base64," prefix and returns only the body', async () => {
    const stripped = await captureToBase64Stripped();
    expect(typeof stripped).toBe('string');
    expect(stripped.startsWith('data:')).toBe(false);
    expect(stripped.length).toBeGreaterThan(0);
  });

  it('round-trips: prefix + stripped equals the full data URL', async () => {
    // Reset the toBlob mock so both captures see the same deterministic body.
    mockToBlob.mockImplementation(
      (cb: (b: Blob | null) => void) => cb(makeMockPngBlob('FIXED_PNG_PAYLOAD')),
    );
    const stripped = await captureToBase64Stripped();
    const full = await captureToBase64();
    expect(`data:image/png;base64,${stripped}`).toBe(full);
  });
});

describe('captureCurrentViewAsFile', () => {
  it('returns a File with type image/png and default name "screenshot.png"', async () => {
    const file = await captureCurrentViewAsFile();
    expect(file).toBeInstanceOf(File);
    expect(file.name).toBe('screenshot.png');
    expect(file.type).toBe('image/png');
    expect(file.size).toBeGreaterThan(0);
  });

  it('honours a custom filename argument', async () => {
    const file = await captureCurrentViewAsFile('crash-2026-06-29.png');
    expect(file.name).toBe('crash-2026-06-29.png');
    expect(file.type).toBe('image/png');
  });
});

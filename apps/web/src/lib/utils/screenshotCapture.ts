/**
 * Screenshot capture — `html2canvas` wrapper for the FeedbackHub flow.
 *
 * Spec: docs/specs/2026-06-28-crash-report-feedback-hub-design.md §8.3
 * Plan: docs/superpowers/plans/2026-06-28-crash-report-feedback-hub.md Task 8.2
 *
 * Four flavours of "current view → PNG" so callers can pick the right
 * container for their transport:
 *
 *   - `captureCurrentView()`        → `Blob` (the canonical form)
 *   - `captureToBase64()`           → `data:image/png;base64,…` data URL
 *                                     (drop straight into `<img src>` or
 *                                     clipboard-as-text fallback).
 *   - `captureToBase64Stripped()`   → bare base64 body, suitable for backend
 *                                     transmission as `screenshot_b64`
 *                                     without the redundant data URL prefix.
 *   - `captureCurrentViewAsFile()`  → `File` for `FormData` / `input[type=file]`
 *                                     handoff (drag-and-drop staging area).
 *
 * Drawer-self-screenshot guard: every wrapper passes `ignoreElements` to
 * html2canvas with the rule "skip anything carrying `.no-screenshot`".
 * `FeedbackHubDrawer` adds this class so the drawer itself never bleeds
 * into the user's own screenshot.
 *
 * Error policy: failures (html2canvas rejection, tainted canvas → null blob)
 * are propagated as rejected Promises. We deliberately do NOT silently
 * resolve with a placeholder — a missing screenshot must surface to the
 * caller so it can show "スクショ取得に失敗しました" instead of attaching
 * empty bytes to a feedback Issue.
 */
import html2canvas from 'html2canvas';

/** Data URL prefix for PNGs — used by the strip wrapper. */
const PNG_DATA_URL_PREFIX = 'data:image/png;base64,';

/**
 * Options handed to html2canvas. Kept as a module-private constant so every
 * wrapper sees the same configuration (avoids "captureToBase64 drifted from
 * captureCurrentView" bugs when the option set evolves).
 */
const HTML2CANVAS_OPTIONS = {
  backgroundColor: '#ffffff',
  scale: 1,
  logging: false,
  ignoreElements: (el: Element): boolean => el.classList.contains('no-screenshot'),
} as const;

/**
 * Capture the entire `document.body` to a PNG `Blob`.
 *
 * @throws if html2canvas itself rejects (e.g. cross-origin tainted canvas).
 * @throws if `canvas.toBlob` calls back with `null` (browser refused to
 *         encode — usually a taint check). We surface this as a Promise
 *         rejection rather than masking it as a zero-byte blob.
 * @throws if `canvas.toBlob` calls back with a 0-byte Blob. The header
 *         "Error policy" promises empty bytes surface as rejection — an
 *         empty PNG attached to a feedback Issue looks like success to the
 *         user but carries zero diagnostic value, which is worse than no
 *         screenshot at all.
 */
export async function captureCurrentView(): Promise<Blob> {
  const canvas = await html2canvas(document.body, HTML2CANVAS_OPTIONS);
  return new Promise<Blob>((resolve, reject) => {
    try {
      canvas.toBlob((blob: Blob | null) => {
        if (blob === null) {
          reject(
            new Error(
              'screenshotCapture: canvas.toBlob returned null (canvas may be tainted by cross-origin content)',
            ),
          );
          return;
        }
        if (blob.size === 0) {
          reject(
            new Error('screenshotCapture: canvas produced empty PNG'),
          );
          return;
        }
        resolve(blob);
      }, 'image/png');
    } catch (err) {
      // Defensive: canvas.toBlob is synchronous in practice but the spec
      // allows it to throw on disallowed mime types. Funnel into the
      // promise so callers see one consistent rejection contract.
      reject(err);
    }
  });
}

/**
 * Read a Blob into a `data:image/png;base64,…` data URL string.
 *
 * Uses `FileReader.readAsDataURL` (rather than `btoa(String.fromCharCode(...))`)
 * to avoid the `Maximum call stack size exceeded` you can hit when expanding
 * a multi-MB Uint8Array via `String.fromCharCode(...arr)` — a real
 * full-viewport screenshot easily exceeds that limit on a 4K display.
 */
function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const result = reader.result;
      if (typeof result === 'string') {
        resolve(result);
        return;
      }
      reject(
        new Error('screenshotCapture: FileReader produced a non-string result'),
      );
    };
    reader.onerror = () =>
      reject(reader.error ?? new Error('screenshotCapture: FileReader failed'));
    reader.readAsDataURL(blob);
  });
}

/**
 * Capture and return the screenshot as a base64-encoded data URL string.
 *
 * Format: `data:image/png;base64,<body>`. Drop straight into an `<img src>`
 * or hand to clipboard-as-text fallbacks. For backend transmission prefer
 * {@link captureToBase64Stripped} — sending the prefix bloats the payload
 * and forces the server to strip it anyway.
 */
export async function captureToBase64(): Promise<string> {
  const blob = await captureCurrentView();
  return blobToDataUrl(blob);
}

/**
 * Same as {@link captureToBase64} but strips the `data:image/png;base64,`
 * prefix. The bare base64 body is the canonical wire format for the
 * backend's `screenshot_b64` field (spec §8.3 / FeedbackHub API).
 *
 * Defensive: if `blobToDataUrl` ever returns a non-PNG data URL (browser
 * downgraded the mime), we still strip whatever prefix is present so the
 * caller always sees a clean base64 body.
 */
export async function captureToBase64Stripped(): Promise<string> {
  const dataUrl = await captureToBase64();
  if (dataUrl.startsWith(PNG_DATA_URL_PREFIX)) {
    return dataUrl.slice(PNG_DATA_URL_PREFIX.length);
  }
  // Generic fallback: strip "data:<mime>;base64," if present.
  const commaIdx = dataUrl.indexOf(',');
  if (dataUrl.startsWith('data:') && commaIdx !== -1) {
    return dataUrl.slice(commaIdx + 1);
  }
  return dataUrl;
}

/**
 * Capture the screenshot and wrap the Blob in a `File` so it can be fed to
 * `<input type="file">` / `FormData` / drag-and-drop staging areas.
 *
 * @param filename — default `'screenshot.png'`. Pass something like
 *                   `crash-${crashId}.png` if you want the user's GitHub
 *                   upload to carry meaningful metadata.
 */
export async function captureCurrentViewAsFile(
  filename = 'screenshot.png',
): Promise<File> {
  const blob = await captureCurrentView();
  return new File([blob], filename, { type: 'image/png' });
}

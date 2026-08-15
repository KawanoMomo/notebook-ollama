/**
 * 出典パネルの幅(px)の永続化とクランプ。
 *
 * 既定の 360px は本文を読むには狭い。ドラッグで比率を変えられるようにし、
 * 選んだ幅は localStorage に覚える(毎回広げ直さずに済む)。
 */
const KEY = 'notebook-ollama:viewer-width';

export const MIN_VIEWER_WIDTH = 280;
export const DEFAULT_VIEWER_WIDTH = 360;
/** ウィンドウ幅に対する上限。チャット側が潰れないようにする。 */
export const MAX_VIEWER_RATIO = 0.7;

export function clampViewerWidth(width: number, windowWidth: number): number {
  const max = Math.max(MIN_VIEWER_WIDTH, Math.floor(windowWidth * MAX_VIEWER_RATIO));
  if (!Number.isFinite(width)) return DEFAULT_VIEWER_WIDTH;
  return Math.min(max, Math.max(MIN_VIEWER_WIDTH, Math.round(width)));
}

export function loadViewerWidth(): number {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULT_VIEWER_WIDTH;
    const n = Number(raw);
    return Number.isFinite(n) ? n : DEFAULT_VIEWER_WIDTH;
  } catch {
    return DEFAULT_VIEWER_WIDTH;
  }
}

export function saveViewerWidth(width: number): void {
  try {
    localStorage.setItem(KEY, String(Math.round(width)));
  } catch {
    // プライベートモード等で書けなくても機能は続行する
  }
}

import type { PageRect } from '$lib/api/pages';

/**
 * 矩形を画像の自然サイズに対する百分率へ変換する。
 *
 * 画像は width:100% で縮小表示し、拡大時は dpi を上げて描画し直すため、
 * ピクセル固定で重ねると必ずズレる。百分率なら縮尺に依存しない。
 */
export function toPercentBox(
  rect: PageRect,
  naturalWidth: number,
  naturalHeight: number,
): { left: string; top: string; width: string; height: string } {
  if (!naturalWidth || !naturalHeight) {
    // 画像がまだ読み込まれていない(naturalWidth=0)。描画しても意味が無いので潰す。
    return { left: '0%', top: '0%', width: '0%', height: '0%' };
  }
  const pct = (v: number, total: number) => Math.max(0, Math.min(100, (v / total) * 100));
  const left = pct(rect.x, naturalWidth);
  const top = pct(rect.y, naturalHeight);
  return {
    left: `${left}%`,
    top: `${top}%`,
    width: `${Math.min(100 - left, pct(rect.w, naturalWidth))}%`,
    height: `${Math.min(100 - top, pct(rect.h, naturalHeight))}%`,
  };
}

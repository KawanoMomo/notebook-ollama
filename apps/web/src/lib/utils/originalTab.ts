// 原本 PDF を持つソース種別。pptx は取込時に COM で PDF を併産している。
const ORIGINAL_KINDS = new Set(['pdf', 'pptx']);

/**
 * 原本タブを出してよいか。
 * PDF 由来のソースで、かつチャンクがページ番号を持つときだけ出す
 * (録音・テキスト・Web 取り込みには原本ページが存在しない)。
 */
export function canShowOriginal(
  kind: string | undefined,
  page: number | null | undefined,
): boolean {
  if (!kind || !ORIGINAL_KINDS.has(kind)) return false;
  return typeof page === 'number' && page > 0;
}

const TAB_KEY = 'notebook-ollama:viewer-tab';

export type ViewerTab = 'text' | 'original';

/**
 * 最後に選んだタブ。引用を渡り歩いても表示が勝手に戻らないよう覚えておく。
 * 原本を出せないチャンク(録音など)では呼び出し側がテキストへ倒す。
 */
export function loadViewerTab(): ViewerTab {
  try {
    return localStorage.getItem(TAB_KEY) === 'original' ? 'original' : 'text';
  } catch {
    return 'text';
  }
}

export function saveViewerTab(tab: ViewerTab): void {
  try {
    localStorage.setItem(TAB_KEY, tab);
  } catch {
    // 書けなくても表示は続行する
  }
}

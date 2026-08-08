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

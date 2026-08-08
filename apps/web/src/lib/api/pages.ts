export interface PageRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface PageRectsResult {
  rects: PageRect[];
  /** 'asset' = 表・図の bbox 由来 / 'quote' = 原文検索由来 / 'none' = 特定できず */
  source: 'asset' | 'quote' | 'none';
  /** 矩形と同じ dpi でのページ寸法(px)。百分率計算の基準にする。 */
  page_width: number;
  page_height: number;
}

/** 原本ページ画像の URL。dpi はサーバ側で 150/300 に限定されている。 */
export function pageImageUrl(
  notebookId: string,
  sourceId: string,
  page: number,
  dpi = 150,
): string {
  return `/api/notebooks/${notebookId}/sources/${sourceId}/pages/${page}?dpi=${dpi}`;
}

/**
 * 根拠箇所の矩形を取得する。
 * 取れなくても原本の閲覧自体は妨げないよう、失敗時は例外を投げず空を返す。
 */
export async function fetchPageRects(
  notebookId: string,
  sourceId: string,
  page: number,
  chunkId: string,
  quote: string,
  dpi = 150,
): Promise<PageRectsResult> {
  try {
    const res = await fetch(
      `/api/notebooks/${notebookId}/sources/${sourceId}/pages/${page}/rects`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ chunk_id: chunkId, quote, dpi }),
      },
    );
    if (!res.ok) return { rects: [], source: 'none', page_width: 0, page_height: 0 };
    return await res.json();
  } catch {
    return { rects: [], source: 'none', page_width: 0, page_height: 0 };
  }
}

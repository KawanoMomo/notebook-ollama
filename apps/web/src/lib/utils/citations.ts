import type { Citation } from '$lib/api/types';

/** markdown-it が出力するコード領域 (<code> / <pre>)。中の [^n] は本文ではない。 */
const CODE_REGION_RE = /<(code|pre)\b[\s\S]*?<\/\1>/gi;

/**
 * [^n] マーカーをバッジへ置換する。
 *
 * 計数の基準面は「コード領域を除外した本文」。BE の iter_claim_occurrences と
 * 同じ規則にすることで answer_occurrence の対応が崩れないようにしている。
 * 対の検証は tests/unit/citationCodeRegions.test.ts(実際に markdown-it を通す)。
 */
export function injectCitationBadges(html: string, citations: Citation[]): string {
  const byN = new Map(citations.map((c) => [c.n, c]));
  let occurrence = 0;

  const replaceOutsideCode = (segment: string): string =>
    segment.replace(/\[\^(\d+)\]/g, (_m, nStr) => {
      const n = Number(nStr);
      const c = byN.get(n);
      if (!c) return `[^${n}]`;
      const current = occurrence++;
      const span = c.spans?.find((s) => s.answer_occurrence === current);
      const label = span?.ordinal != null ? `${n}-${span.ordinal}` : `${n}`;
      const title = `${c.source_title}${c.location ? ' / ' + c.location : ''}`;
      return (
        `<button class="citation-badge" data-n="${n}" data-occurrence="${current}"` +
        ` title="${escapeAttr(title)}">${label}</button>`
      );
    });

  let out = '';
  let cursor = 0;
  for (const m of html.matchAll(CODE_REGION_RE)) {
    const at = m.index ?? 0;
    out += replaceOutsideCode(html.slice(cursor, at));
    out += m[0]; // コード領域はそのまま
    cursor = at + m[0].length;
  }
  out += replaceOutsideCode(html.slice(cursor));
  return out;
}

function escapeAttr(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}

/** Extract list of citation numbers in textual order. */
export function listCitationNumbers(text: string): number[] {
  const seen = new Set<number>();
  const out: number[] = [];
  for (const m of text.matchAll(/\[\^(\d+)\]/g)) {
    const n = Number(m[1]);
    if (!seen.has(n)) {
      seen.add(n);
      out.push(n);
    }
  }
  return out;
}

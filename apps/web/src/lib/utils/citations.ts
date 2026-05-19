import type { Citation } from '$lib/api/types';

/**
 * Replace [^n] markers in HTML with clickable citation badges.
 * Returns HTML with badge spans.
 */
export function injectCitationBadges(html: string, citations: Citation[]): string {
  const byN = new Map(citations.map((c) => [c.n, c]));
  return html.replace(/\[\^(\d+)\]/g, (_match, nStr) => {
    const n = Number(nStr);
    const c = byN.get(n);
    if (!c) return `[^${n}]`;
    const title = `${c.source_title}${c.location ? ' / ' + c.location : ''}`;
    return `<button class="citation-badge" data-n="${n}" title="${escapeAttr(title)}">${n}</button>`;
  });
}

function escapeAttr(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}

/**
 * Extract list of citation numbers in textual order.
 */
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

import type { EvidenceSpan } from '$lib/api/types';

export interface Segment {
  text: string;
  span: EvidenceSpan | null;
  active: boolean;
}

/**
 * チャンク本文をスパン境界で分割する。
 * activeOccurrence に一致するスパンだけ active=true(濃いマーカー)。
 */
export function splitBySpans(
  text: string,
  spans: EvidenceSpan[],
  activeOccurrence: number | null,
): Segment[] {
  const valid = spans.filter((s) => s.start >= 0 && s.end > s.start && s.end <= text.length);

  // 隣り合う主張の根拠は実データでしばしば重なる(例: [0:122] と [25:216])。
  // 素朴に「先勝ち」で落とすと、2番目以降のバッジを押しても何も光らない。
  // **選択中のスパンを最優先で確保**し、それと重ならないものだけを併せて描く。
  const active = valid.find((s) => activeOccurrence !== null && s.answer_occurrence === activeOccurrence);
  const overlaps = (a: EvidenceSpan, b: EvidenceSpan) => a.start < b.end && b.start < a.end;
  const kept = active
    ? [active, ...valid.filter((s) => s !== active && !overlaps(s, active))]
    : [...valid];
  kept.sort((a, b) => a.start - b.start);

  const segments: Segment[] = [];
  let cursor = 0;
  for (const s of kept) {
    if (s.start < cursor) continue; // 残った同士がなお重なる場合は先勝ち
    if (s.start > cursor) {
      segments.push({ text: text.slice(cursor, s.start), span: null, active: false });
    }
    segments.push({
      text: text.slice(s.start, s.end),
      span: s,
      active: activeOccurrence !== null && s.answer_occurrence === activeOccurrence,
    });
    cursor = s.end;
  }
  if (cursor < text.length) {
    segments.push({ text: text.slice(cursor), span: null, active: false });
  }
  return segments.length > 0 ? segments : [{ text, span: null, active: false }];
}

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
  const valid = spans
    .filter((s) => s.start >= 0 && s.end > s.start && s.end <= text.length)
    .sort((a, b) => a.start - b.start);

  const segments: Segment[] = [];
  let cursor = 0;
  for (const s of valid) {
    if (s.start < cursor) continue; // 重なりは先勝ち
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

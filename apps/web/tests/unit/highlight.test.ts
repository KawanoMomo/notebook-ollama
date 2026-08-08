import { describe, expect, it } from 'vitest';
import { splitBySpans } from '../../src/lib/utils/highlight';
import type { EvidenceSpan } from '../../src/lib/api/types';

const span = (o: number, ord: number, s: number, e: number): EvidenceSpan => ({
  answer_occurrence: o,
  ordinal: ord,
  start: s,
  end: e,
  quote: '',
  method: 'lexical',
});

describe('splitBySpans', () => {
  it('スパンが無ければ1セグメント', () => {
    const got = splitBySpans('abcdef', [], null);
    expect(got).toEqual([{ text: 'abcdef', span: null, active: false }]);
  });

  it('スパン前後を分割する', () => {
    const got = splitBySpans('abcdef', [span(0, 1, 2, 4)], 0);
    expect(got.map((s) => s.text)).toEqual(['ab', 'cd', 'ef']);
    expect(got[1].active).toBe(true);
  });

  it('選択中でないスパンは active=false', () => {
    const got = splitBySpans('abcdef', [span(1, 1, 2, 4)], 0);
    expect(got[1].active).toBe(false);
  });

  it('複数スパンを開始位置順に並べる', () => {
    const got = splitBySpans('abcdefgh', [span(1, 2, 5, 7), span(0, 1, 1, 3)], 1);
    expect(got.map((s) => s.text)).toEqual(['a', 'bc', 'de', 'fg', 'h']);
    expect(got[1].active).toBe(false);
    expect(got[3].active).toBe(true);
  });

  it('範囲外・逆転したスパンは無視する', () => {
    const got = splitBySpans('abc', [span(0, 1, 5, 9), span(0, 2, 3, 1)], 0);
    expect(got).toEqual([{ text: 'abc', span: null, active: false }]);
  });

  it('重なったスパンは後のものを捨てる', () => {
    const got = splitBySpans('abcdef', [span(0, 1, 1, 4), span(1, 1, 2, 5)], 0);
    expect(got.map((s) => s.text)).toEqual(['a', 'bcd', 'ef']);
  });
});

describe('splitBySpans — 重なるスパン(実データで発生)', () => {
  const overlapping: EvidenceSpan[] = [
    { answer_occurrence: 0, ordinal: 1, start: 0, end: 12, quote: '', method: 'lexical' },
    { answer_occurrence: 1, ordinal: 2, start: 5, end: 20, quote: '', method: 'lexical' },
    { answer_occurrence: 2, ordinal: 3, start: 16, end: 30, quote: '', method: 'lexical' },
  ];
  const text = 'x'.repeat(40);

  it('選択中のスパンは重なっていても必ず描画される', () => {
    for (const active of [0, 1, 2]) {
      const got = splitBySpans(text, overlapping, active);
      const actives = got.filter((s) => s.active);
      expect(actives, `occurrence ${active} が描画されない`).toHaveLength(1);
      const span = overlapping.find((s) => s.answer_occurrence === active)!;
      expect(actives[0].text).toBe(text.slice(span.start, span.end));
    }
  });

  it('選択中と重なる他スパンは落とすが、重ならないものは残す', () => {
    const got = splitBySpans(text, overlapping, 2);
    const marks = got.filter((s) => s.span !== null);
    // active(16-30)と重ならない 0-12 は残り、重なる 5-20 は落ちる
    expect(marks).toHaveLength(2);
    expect(marks.map((m) => m.text)).toEqual([text.slice(0, 12), text.slice(16, 30)]);
  });

  it('セグメントの連結は常に元テキストと一致する', () => {
    for (const active of [null, 0, 1, 2]) {
      const got = splitBySpans(text, overlapping, active);
      expect(got.map((s) => s.text).join('')).toBe(text);
    }
  });
});

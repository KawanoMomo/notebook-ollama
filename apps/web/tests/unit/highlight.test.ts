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

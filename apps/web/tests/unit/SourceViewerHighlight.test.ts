import { describe, expect, it } from 'vitest';
import { splitBySpans } from '../../src/lib/utils/highlight';
import type { Citation } from '../../src/lib/api/types';

/**
 * SourceViewer は API 依存が重いため、描画に使う純ロジックを検証する。
 * (コンポーネント全体の実機確認は evaluator のスクリーンショットで担保する)
 */
const citation = {
  n: 3,
  chunk_id: 'c1',
  spans: [
    { answer_occurrence: 0, ordinal: 1, start: 0, end: 5, quote: 'ABCDE', method: 'lexical' },
    { answer_occurrence: 2, ordinal: 2, start: 8, end: 12, quote: 'IJKL', method: 'lexical' },
  ],
} as unknown as Citation;

describe('出典パネルのハイライト対象', () => {
  it('選択中の出現だけが active になる', () => {
    const got = splitBySpans('ABCDEFGHIJKLMN', citation.spans!, 2);
    const actives = got.filter((s) => s.active).map((s) => s.text);
    expect(actives).toEqual(['IJKL']);
  });

  it('同じチャンクの他スパンも淡色で描画対象に残る', () => {
    const got = splitBySpans('ABCDEFGHIJKLMN', citation.spans!, 2);
    const marks = got.filter((s) => s.span !== null).map((s) => s.text);
    expect(marks).toEqual(['ABCDE', 'IJKL']);
  });

  it('spans が空なら分割されない(従来表示へのフォールバック)', () => {
    const got = splitBySpans('ABCDEFGHIJKLMN', [], null);
    expect(got).toHaveLength(1);
    expect(got[0].span).toBeNull();
  });
});

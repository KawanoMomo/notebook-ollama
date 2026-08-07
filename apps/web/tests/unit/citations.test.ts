import { describe, expect, it } from 'vitest';
import { injectCitationBadges, listCitationNumbers } from '$lib/utils/citations';
import type { Citation } from '$lib/api/types';

const cite = (n: number, spans: Citation['spans'] = []): Citation => ({
  n,
  chunk_id: `c${n}`,
  source_id: `s${n}`,
  source_title: `S${n}`,
  location: `p.${n}`,
  url_or_path: null,
  snippet: '',
  audio_source_id: null,
  audio_start_ms: null,
  audio_channel: null,
  spans,
});

describe('citations', () => {
  it('injects badge spans', () => {
    const html = injectCitationBadges('hello [^1] world', [cite(1)]);
    expect(html).toContain('class="citation-badge"');
    expect(html).toContain('data-n="1"');
  });

  it('passes through unknown citation numbers', () => {
    expect(injectCitationBadges('see [^9]', [cite(1)])).toContain('[^9]');
  });

  it('lists numbers in textual order without duplicates', () => {
    expect(listCitationNumbers('a[^2] b[^1] c[^2]')).toEqual([2, 1]);
  });
});

describe('injectCitationBadges — 枝番', () => {
  it('spans があれば出現ごとに枝番ラベルを振る', () => {
    const c = cite(3, [
      { answer_occurrence: 0, ordinal: 1, start: 0, end: 3, quote: 'abc', method: 'lexical' },
      { answer_occurrence: 1, ordinal: 2, start: 5, end: 8, quote: 'def', method: 'lexical' },
    ]);
    const html = injectCitationBadges('<p>A[^3]。B[^3]。</p>', [c]);
    expect(html).toContain('>3-1<');
    expect(html).toContain('>3-2<');
    expect(html).toContain('data-occurrence="0"');
    expect(html).toContain('data-occurrence="1"');
  });

  it('spans が無ければ従来どおり番号のみ', () => {
    const html = injectCitationBadges('<p>A[^3]。</p>', [cite(3)]);
    expect(html).toContain('>3<');
    expect(html).not.toContain('3-1');
  });

  it('一部の出現だけ未特定でも対応がズレない', () => {
    const c = cite(3, [
      { answer_occurrence: 1, ordinal: 1, start: 5, end: 8, quote: 'def', method: 'lexical' },
    ]);
    const html = injectCitationBadges('<p>A[^3]。B[^3]。</p>', [c]);
    // 1つ目の出現は枝番なし、2つ目が 3-1
    const first = html.indexOf('data-occurrence="0"');
    const second = html.indexOf('data-occurrence="1"');
    expect(first).toBeGreaterThan(-1);
    expect(second).toBeGreaterThan(first);
    expect(html.slice(first, second)).toContain('>3<');
    expect(html.slice(second)).toContain('>3-1<');
  });

  it('インデント式コードブロック(4スペース)内のマーカーも数えない', () => {
    // markdown-it は 4スペース始まりの行も <pre><code> にする。BE の mask_code_regions と
    // 対になるケース。どちらかが欠けると answer_occurrence が全域でズレる。
    const c = cite(1, [
      { answer_occurrence: 0, ordinal: 1, start: 0, end: 3, quote: 'abc', method: 'lexical' },
    ]);
    const html = injectCitationBadges('<p>本文[^1]。</p><pre><code>sample = data[^1]\n</code></pre>', [c]);
    expect(html).toContain('data-occurrence="0"');
    expect(html).not.toContain('data-occurrence="1"');
  });

  it('コードブロック内のマーカーは数えずバッジ化もしない', () => {
    const c = cite(1, [
      { answer_occurrence: 0, ordinal: 1, start: 0, end: 3, quote: 'abc', method: 'lexical' },
    ]);
    const html = injectCitationBadges('<p>本文[^1]。</p><pre><code>[^1]</code></pre>', [c]);
    expect(html).toContain('data-occurrence="0"');
    expect(html).not.toContain('data-occurrence="1"');
    expect(html).toContain('<code>[^1]</code>');
  });
});

describe('injectCitationBadges — citations に無い [^n] があっても出現番号がズレない', () => {
  it('未知の n もカウントに含める(BE と基準面を揃える)', () => {
    // build_citations は specs に無い n を落とすが、回答本文からマーカーは消えない。
    // LLM が幻覚で [^7] を出すとこの形になる。
    const c = cite(1, [
      { answer_occurrence: 1, ordinal: 1, start: 0, end: 3, quote: 'abc', method: 'lexical' },
      { answer_occurrence: 2, ordinal: 2, start: 5, end: 8, quote: 'def', method: 'lexical' },
    ]);
    const html = injectCitationBadges('<p>幻[^7]。A[^1]。B[^1]。</p>', [c]);
    // [^7] は素通しするが occurrence は消費するので、[^1] は 1 と 2 になる
    expect(html).toContain('[^7]');
    expect(html).toContain('data-occurrence="1"');
    expect(html).toContain('data-occurrence="2"');
    expect(html).not.toContain('data-occurrence="0"');
    // 枝番も BE の answer_occurrence とそのまま対応する
    expect(html).toContain('>1-1<');
    expect(html).toContain('>1-2<');
  });
});

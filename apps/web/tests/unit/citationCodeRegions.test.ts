import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { injectCitationBadges } from '$lib/utils/citations';
import { renderMarkdown } from '$lib/utils/markdown';
import type { Citation } from '$lib/api/types';

/**
 * BE (core/generation/evidence_spans.mask_code_regions) と FE で、コード領域を
 * 除いた [^n] の並びが一致することを確認する。
 *
 * ここは**手書きの HTML 文字列ではなく実際に markdown-it を通した HTML** に対して
 * 数える。手書き HTML では「markdown-it が何をコードとみなすか」のズレを一切
 * 検出できず、それがまさに誤帰属 (別の主張の根拠を自信満々に表示する) の原因に
 * なるため。ケースは BE と共有する:
 *   tests/fixtures/code_region_cases.json
 *   tests/unit/test_evidence_spans_code_regions.py (BE 側の対)
 */
interface Case {
  name: string;
  why?: string;
  markdown: string;
  expected: number[];
}

// vitest の root は apps/web。リポジトリ直下の共有フィクスチャを見る。
const fixture = JSON.parse(
  readFileSync(resolve(process.cwd(), '../../tests/fixtures/code_region_cases.json'), 'utf8'),
) as { cases: Case[] };

const cite = (n: number): Citation =>
  ({
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
  }) as Citation;

const CITATIONS = [1, 2, 3, 4, 5, 9].map(cite);

/** バッジ化された = コード領域の外だと FE が判断した [^n] の並び。 */
function badgedNumbers(markdown: string): number[] {
  const html = injectCitationBadges(renderMarkdown(markdown), CITATIONS);
  return [...html.matchAll(/data-n="(\d+)"/g)].map((m) => Number(m[1]));
}

describe('コード領域の基準面が BE と一致する', () => {
  for (const c of fixture.cases) {
    it(`${c.name}${c.why ? ` — ${c.why}` : ''}`, () => {
      expect(badgedNumbers(c.markdown)).toEqual(c.expected);
    });
  }
});

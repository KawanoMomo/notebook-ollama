import { describe, expect, it } from 'vitest';
import { injectCitationBadges, listCitationNumbers } from '$lib/utils/citations';
import type { Citation } from '$lib/api/types';

const cite = (n: number): Citation => ({
  n,
  chunk_id: `c${n}`,
  source_id: `s${n}`,
  source_title: `S${n}`,
  location: `p.${n}`,
  url_or_path: null,
  snippet: '',
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

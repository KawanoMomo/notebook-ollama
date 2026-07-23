import { describe, expect, it } from 'vitest';
import { sanitizeTableHtml } from '$lib/utils/tableHtml';

describe('sanitizeTableHtml', () => {
  it('table/thead/tbody/tr/th/td は保持する', () => {
    const html =
      '<table><thead><tr><th>A</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table>';
    const out = sanitizeTableHtml(html);
    expect(out).toContain('<table>');
    expect(out).toContain('<thead>');
    expect(out).toContain('<tbody>');
    expect(out).toContain('<tr>');
    expect(out).toContain('<th>A</th>');
    expect(out).toContain('<td>1</td>');
  });

  it('許可外タグ(script/div等)は unwrap され、子ノードは残る', () => {
    const html = '<table><tbody><tr><td><div>text</div><script>alert(1)</script></td></tr></tbody></table>';
    const out = sanitizeTableHtml(html);
    expect(out).not.toContain('<div>');
    expect(out).not.toContain('<script>');
    expect(out).toContain('text');
  });

  it('rowspan/colspan 属性は保持する', () => {
    const html = '<table><tbody><tr><td rowspan="2" colspan="3">x</td></tr></tbody></table>';
    const out = sanitizeTableHtml(html);
    expect(out).toContain('rowspan="2"');
    expect(out).toContain('colspan="3"');
  });

  it('rowspan/colspan 以外の属性(style, onclick等)は除去する', () => {
    const html =
      '<table style="x"><tbody><tr><td onclick="evil()" style="color:red" class="c">x</td></tr></tbody></table>';
    const out = sanitizeTableHtml(html);
    expect(out).not.toContain('onclick');
    expect(out).not.toContain('style=');
    expect(out).not.toContain('class=');
  });
});

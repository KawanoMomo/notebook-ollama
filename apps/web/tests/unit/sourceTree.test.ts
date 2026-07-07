/**
 * sourceTree.orderWithChildren — 親子ツリー表示のための並べ替え純関数。
 * 仕様: docs/specs/2026-07-06-presentation-mode-design.md, Task 10 brief。
 *
 * v1 は1階層に平坦化(親の直後に子を depth=1 で並べる)。
 * - リンク無しソース・親がリスト外のソースは depth=0 で元の順序のまま
 * - 循環等の壊れたリンクデータでも全ソースを欠落なく出力し、無限ループしない
 */
import { describe, expect, it } from 'vitest';
import { orderWithChildren } from '$lib/utils/sourceTree';
import type { Source, SourceLink } from '$lib/api/types';

function makeSource(id: string, overrides: Partial<Source> = {}): Source {
  return {
    id,
    notebook_id: 'nb1',
    kind: 'pdf',
    title: `資料${id}`,
    origin: null,
    status: 'ready',
    error_msg: null,
    bytes: null,
    page_count: null,
    chunk_count: 1,
    created_at: 't',
    updated_at: 't',
    ...overrides,
  };
}

function makeLink(childId: string, parentId: string): SourceLink {
  return {
    id: `link-${childId}-${parentId}`,
    notebook_id: 'nb1',
    parent_source_id: parentId,
    child_source_id: childId,
    relation: 'manual',
    meta: null,
    created_at: 't',
  };
}

describe('orderWithChildren', () => {
  it('親の直後に子が並ぶ', () => {
    const p = makeSource('p');
    const c = makeSource('c');
    const rows = orderWithChildren([p, c], [makeLink('c', 'p')]);
    expect(rows).toEqual([
      { source: p, depth: 0 },
      { source: c, depth: 1 },
    ]);
  });

  it('子が複数の場合は元の(=作成)順序で親の直後に並ぶ', () => {
    const p = makeSource('p');
    const c1 = makeSource('c1');
    const c2 = makeSource('c2');
    const c3 = makeSource('c3');
    const rows = orderWithChildren(
      [p, c1, c2, c3],
      [makeLink('c1', 'p'), makeLink('c2', 'p'), makeLink('c3', 'p')],
    );
    expect(rows).toEqual([
      { source: p, depth: 0 },
      { source: c1, depth: 1 },
      { source: c2, depth: 1 },
      { source: c3, depth: 1 },
    ]);
  });

  it('リンクが無いソースはそのままの順序・depth=0で並ぶ', () => {
    const a = makeSource('a');
    const b = makeSource('b');
    const rows = orderWithChildren([a, b], []);
    expect(rows).toEqual([
      { source: a, depth: 0 },
      { source: b, depth: 0 },
    ]);
  });

  it('子の親が同一リスト内に無い(フィルタ済)場合は depth=0 で扱う', () => {
    const c = makeSource('c');
    const rows = orderWithChildren([c], [makeLink('c', 'ghost-parent')]);
    expect(rows).toEqual([{ source: c, depth: 0 }]);
  });

  it('循環したリンクデータでも無限ループせず全ソースを欠落なく出力する', () => {
    const a = makeSource('a');
    const b = makeSource('b');
    const rows = orderWithChildren([a, b], [makeLink('a', 'b'), makeLink('b', 'a')]);
    expect(rows).toHaveLength(2);
    expect(new Set(rows.map((r) => r.source.id))).toEqual(new Set(['a', 'b']));
  });
});

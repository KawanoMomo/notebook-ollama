import type { Source, SourceLink } from '$lib/api/types';

export interface SourceRow { source: Source; depth: 0 | 1 }

/** 親の直後に子をインデント表示するための並べ替え(v1: 1階層に平坦化)。 */
export function orderWithChildren(sources: Source[], links: SourceLink[]): SourceRow[] {
  const parentOf = new Map(links.map((l) => [l.child_source_id, l.parent_source_id]));
  const byId = new Map(sources.map((s) => [s.id, s]));
  const childrenOf = new Map<string, Source[]>();
  const roots: Source[] = [];
  for (const s of sources) {
    const p = parentOf.get(s.id);
    if (p && byId.has(p)) {
      const arr = childrenOf.get(p) ?? [];
      arr.push(s);
      childrenOf.set(p, arr);
    } else {
      roots.push(s);
    }
  }
  const rows: SourceRow[] = [];
  const seen = new Set<string>();
  for (const r of roots) {
    if (seen.has(r.id)) continue;
    seen.add(r.id);
    rows.push({ source: r, depth: 0 });
    // v1 は1階層表示: 直接の子のみ。子の子はデータ上あり得るが roots 側に出る
    for (const c of childrenOf.get(r.id) ?? []) {
      if (seen.has(c.id)) continue;
      seen.add(c.id);
      rows.push({ source: c, depth: 1 });
    }
  }
  // 防御: 万一 seen 漏れ(壊れたリンクデータ)があっても欠落させない
  for (const s of sources) if (!seen.has(s.id)) rows.push({ source: s, depth: 0 });
  return rows;
}

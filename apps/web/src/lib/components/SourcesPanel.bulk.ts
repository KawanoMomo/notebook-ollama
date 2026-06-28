/**
 * SourcesPanel の「すべてのソース」トライステート行を駆動する純粋関数。
 *
 * 仕様: docs/specs/2026-06-25-source-guide-design.md §2.2
 *  - 全選択 -> state='all',  クリック動作=全解除
 *  - 一部選択 -> state='some', クリック動作=全解除
 *  - 0 件   -> state='none', クリック動作=全選択
 *
 * フィルタ中(検索ボックスに入力あり)は visibleIds を絞った上で渡す。
 */
export type BulkState = 'all' | 'some' | 'none';

export interface BulkInput {
  visibleIds: readonly string[];
  selectedIds: ReadonlySet<string>;
}

export interface BulkResult {
  state: BulkState;
  label: string;
}

export function computeBulkState({ visibleIds, selectedIds }: BulkInput): BulkResult {
  const total = visibleIds.length;
  const selectedCount = visibleIds.reduce(
    (n, id) => (selectedIds.has(id) ? n + 1 : n),
    0,
  );
  const state: BulkState =
    total > 0 && selectedCount === total
      ? 'all'
      : selectedCount === 0
        ? 'none'
        : 'some';
  return { state, label: `${selectedCount} / ${total}` };
}

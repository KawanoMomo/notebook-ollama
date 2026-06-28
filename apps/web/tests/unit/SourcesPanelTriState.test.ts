/**
 * SourcesPanel のトライステート「すべてのソース」行のロジック単体テスト。
 *
 * UI 結合は重いため、行のチェック状態とラベルテキストを決める純粋関数
 * (computeBulkState) を抽出して検証する。SourcesPanel.svelte 側ではこの関数を
 * import して使う(実装も同一ロジックでなければならない)。
 *
 * 仕様: docs/specs/2026-06-25-source-guide-design.md §2.2
 */
import { describe, expect, it } from 'vitest';
import { computeBulkState } from '$lib/components/SourcesPanel.bulk';

describe('computeBulkState', () => {
  it('all selected -> state="all"', () => {
    const r = computeBulkState({
      visibleIds: ['a', 'b', 'c'],
      selectedIds: new Set(['a', 'b', 'c']),
    });
    expect(r.state).toBe('all');
    expect(r.label).toBe('3 / 3');
  });

  it('some selected -> state="some"', () => {
    const r = computeBulkState({
      visibleIds: ['a', 'b', 'c'],
      selectedIds: new Set(['a']),
    });
    expect(r.state).toBe('some');
    expect(r.label).toBe('1 / 3');
  });

  it('none selected -> state="none"', () => {
    const r = computeBulkState({
      visibleIds: ['a', 'b', 'c'],
      selectedIds: new Set(),
    });
    expect(r.state).toBe('none');
    expect(r.label).toBe('0 / 3');
  });

  it('visible subset(filter) considers only the visible IDs', () => {
    // 全 5 件のうち 2 件だけ表示、その 2 件は両方選択中 -> 表示分が all
    const r = computeBulkState({
      visibleIds: ['a', 'b'],
      selectedIds: new Set(['a', 'b', 'c', 'd', 'e']),
    });
    expect(r.state).toBe('all');
    expect(r.label).toBe('2 / 2');
  });

  it('no visible items -> state="none" with 0 / 0', () => {
    const r = computeBulkState({ visibleIds: [], selectedIds: new Set() });
    expect(r.state).toBe('none');
    expect(r.label).toBe('0 / 0');
  });
});

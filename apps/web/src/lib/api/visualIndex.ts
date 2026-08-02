import { request } from './client';

export type VisualIndexUnit = 'page' | 'tile';
export type VisualSearchStrategy = 'hybrid_rrf' | 'visual_only' | 'pixel_native';

export const VISUAL_INDEX_UNITS: VisualIndexUnit[] = ['page', 'tile'];

/** 索引単位の日本語表示名。Modal とトーストで同じ語を使うための単一の出どころ。 */
export const VISUAL_UNIT_LABELS: Record<VisualIndexUnit, string> = {
  page: 'ページ索引',
  tile: 'タイル索引',
};

/** 構築結果トーストの内容。`level` は Toast の ToastLevel に対応する。 */
export interface VisualIndexOutcomeToast {
  message: string;
  level: 'info' | 'success' | 'error';
}

/**
 * 構築結果 (SSE) からトーストの文言と種別を決める純関数。
 *
 * SourcesPanel の $effect に直接書いていたため、分岐 (完了 / 部分失敗 /
 * 対象0件 / 失敗) が自動テストで固定できず目視レビューだけになっていた
 * (issue #28)。SourcesPanel をマウントせずに文言を検証できるよう切り出す。
 */
export function visualIndexOutcomeToast(
  unit: VisualIndexUnit,
  outcome: { kind: 'complete' | 'error' | 'noop'; skippedPages: number },
): VisualIndexOutcomeToast {
  const label = VISUAL_UNIT_LABELS[unit];
  if (outcome.kind === 'complete') {
    if (outcome.skippedPages > 0) {
      // 部分失敗(半滅): 1件でも索引できれば「完了」の見た目になるが、
      // 失敗ページ数を隠すと利用者が気付けない(最終レビュー I4)。
      // ToastLevel は info | success | error の3値しかないため、警告寄りの
      // 文言で 'info' を使う。
      return {
        message: `${label}の構築が完了しました(${outcome.skippedPages}件のページをスキップしました)`,
        level: 'info',
      };
    }
    return { message: `${label}の構築が完了しました`, level: 'success' };
  }
  if (outcome.kind === 'noop') {
    // target_sources == 0: 未索引の対象が無かった。タイル格子等のパラメータを
    // 変えても既に索引済みのソースは再構築対象にならないため、無言で何もしない
    // まま「完了」を装わせない(最終レビュー I3)。
    return {
      message:
        `${label}の対象が0件でした。すべて索引済みです。` +
        'パラメータを変えて作り直すには、先に索引を削除してください。',
      level: 'info',
    };
  }
  return { message: `${label}の構築に失敗しました`, level: 'error' };
}

/** 索引単位ごとの構築状態。 */
export interface VisualUnitStatus {
  built: boolean;
  embedding_model: string | null;
  built_at: string | null;
  indexed_sources: number;
  pending_sources: number;
  building: boolean;
}

export interface VisualIndexStatus {
  extra_available: boolean;
  /** 現在検索に使われている単位(設定画面で切り替える)。 */
  index_unit: VisualIndexUnit;
  search_strategy: VisualSearchStrategy;
  units: Record<VisualIndexUnit, VisualUnitStatus>;
}

export const visualIndexApi = {
  status: (notebookId: string) =>
    request<VisualIndexStatus>(`/api/notebooks/${notebookId}/visual-index`),
  build: (notebookId: string, unit: VisualIndexUnit) =>
    request<{ status: string; unit: VisualIndexUnit }>(
      `/api/notebooks/${notebookId}/visual-index?unit=${unit}`,
      { method: 'POST' },
    ),
  remove: (notebookId: string, unit: VisualIndexUnit) =>
    request<void>(`/api/notebooks/${notebookId}/visual-index?unit=${unit}`, {
      method: 'DELETE',
    }),
};

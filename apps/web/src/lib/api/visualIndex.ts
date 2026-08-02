import { request } from './client';

export type VisualIndexUnit = 'page' | 'tile';
export type VisualSearchStrategy = 'hybrid_rrf' | 'visual_only' | 'pixel_native';

export const VISUAL_INDEX_UNITS: VisualIndexUnit[] = ['page', 'tile'];

/** 索引単位の日本語表示名。Modal とトーストで同じ語を使うための単一の出どころ。 */
export const VISUAL_UNIT_LABELS: Record<VisualIndexUnit, string> = {
  page: 'ページ索引',
  tile: 'タイル索引',
};

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

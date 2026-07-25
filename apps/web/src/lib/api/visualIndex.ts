import { request } from './client';

export interface VisualIndexStatus {
  built: boolean;
  embedding_model: string | null;
  built_at: string | null;
  indexed_sources: number;
  pending_sources: number;
  building: boolean;
  extra_available: boolean;
}

export const visualIndexApi = {
  status: (notebookId: string) =>
    request<VisualIndexStatus>(`/api/notebooks/${notebookId}/visual-index`),
  build: (notebookId: string) =>
    request<{ status: string }>(`/api/notebooks/${notebookId}/visual-index`, { method: 'POST' }),
  remove: (notebookId: string) =>
    request<void>(`/api/notebooks/${notebookId}/visual-index`, { method: 'DELETE' }),
};

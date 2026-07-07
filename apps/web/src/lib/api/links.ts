import { request } from './client';
import type { SourceLink } from './types';

/** 手動リンク API(親設定/解除/一覧)。backend: `apps/api/routers/links.py`。 */
export const linksApi = {
  setParent: (notebookId: string, childId: string, parentId: string) =>
    request<SourceLink>(
      `/api/notebooks/${notebookId}/sources/${childId}/parent`,
      {
        method: 'PUT',
        body: JSON.stringify({ parent_source_id: parentId }),
      },
    ),
  removeParent: (notebookId: string, childId: string) =>
    request<void>(`/api/notebooks/${notebookId}/sources/${childId}/parent`, {
      method: 'DELETE',
    }),
  list: (notebookId: string) =>
    request<SourceLink[]>(`/api/notebooks/${notebookId}/source-links`),
};

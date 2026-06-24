import { request } from './client';
import type { Source } from './types';

export const sourcesApi = {
  list: (notebookId: string) =>
    request<Source[]>(`/api/notebooks/${notebookId}/sources`),
  uploadFile: (notebookId: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return request<Source>(`/api/notebooks/${notebookId}/sources`, {
      method: 'POST',
      body: form,
    });
  },
  uploadUrl: (notebookId: string, url: string) =>
    request<Source>(`/api/notebooks/${notebookId}/sources/url`, {
      method: 'POST',
      body: JSON.stringify({ url }),
    }),
  delete: (notebookId: string, sourceId: string) =>
    request<void>(`/api/notebooks/${notebookId}/sources/${sourceId}`, {
      method: 'DELETE',
    }),
  rename: (notebookId: string, sourceId: string, title: string) =>
    request<Source>(`/api/notebooks/${notebookId}/sources/${sourceId}`, {
      method: 'PATCH',
      body: JSON.stringify({ title }),
    }),
  retry: (notebookId: string, sourceId: string) =>
    request<Source>(`/api/notebooks/${notebookId}/sources/${sourceId}/retry`, {
      method: 'POST',
    }),
  recordingRetry: (notebookId: string, sourceId: string) =>
    request<Source>(
      `/api/notebooks/${notebookId}/recordings/${sourceId}/retry`,
      { method: 'POST' },
    ),
  /** 進行中の録音変換に停止を要求する(次のチェックポイントで中断 → error)。 */
  cancelConversion: (notebookId: string, sourceId: string) =>
    request<{ source_id: string; status: string; cancelled: boolean }>(
      `/api/notebooks/${notebookId}/recordings/${sourceId}/cancel`,
      { method: 'POST' },
    ),
  /** 録音音声のストリーミング URL(same-origin / dev は vite proxy で解決)。 */
  audioUrl: (notebookId: string, sourceId: string, channel: 'mic' | 'system') =>
    `/api/notebooks/${notebookId}/sources/${sourceId}/audio?channel=${channel}`,
};

import { request } from './client';
import type { AssetInfo, Source } from './types';

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
  /** 録音音声のストリーミング URL(same-origin / dev は vite proxy で解決)。
   * channel=mix は BE 側で mic+system を合成(初回は ffmpeg、以後キャッシュ)。 */
  audioUrl: (
    notebookId: string,
    sourceId: string,
    channel: 'mix' | 'mic' | 'system',
  ) => `/api/notebooks/${notebookId}/sources/${sourceId}/audio?channel=${channel}`,
  /** 要約の再生成(summary_status=generating にリセットして BE で再実行)。 */
  summarize: (notebookId: string, sourceId: string) =>
    request<Source>(
      `/api/notebooks/${notebookId}/sources/${sourceId}/summarize`,
      { method: 'POST' },
    ),
  /** 実行中の要約ジョブを中断(summary_status を未生成 None に戻す)。 */
  cancelSummary: (notebookId: string, sourceId: string) =>
    request<Source>(
      `/api/notebooks/${notebookId}/sources/${sourceId}/summarize/cancel`,
      { method: 'POST' },
    ),
  /** ADR 抽出ジョブを起動(Decision Gate → 抽出 or スキップ)。 */
  generateAdr: (notebookId: string, sourceId: string) =>
    request<Source>(
      `/api/notebooks/${notebookId}/sources/${sourceId}/adr`,
      { method: 'POST' },
    ),
  /** ADR 関連列をクリア(やり直し用)。 */
  deleteAdr: (notebookId: string, sourceId: string) =>
    request<void>(
      `/api/notebooks/${notebookId}/sources/${sourceId}/adr`,
      { method: 'DELETE' },
    ),
  reingest: (notebookId: string, sourceId: string) =>
    request<{ status: string }>(
      `/api/notebooks/${notebookId}/sources/${sourceId}/reingest`,
      { method: 'POST' },
    ),
  listAssets: (notebookId: string, sourceId: string) =>
    request<{ assets: AssetInfo[] }>(
      `/api/notebooks/${notebookId}/sources/${sourceId}/assets`,
    ),
  describeFigures: (notebookId: string, sourceId: string) =>
    request<{ status: string }>(
      `/api/notebooks/${notebookId}/sources/${sourceId}/describe-figures`,
      { method: 'POST' },
    ),
  assetImageUrl: (notebookId: string, sourceId: string, assetId: string) =>
    `/api/notebooks/${notebookId}/sources/${sourceId}/assets/${assetId}`,
};

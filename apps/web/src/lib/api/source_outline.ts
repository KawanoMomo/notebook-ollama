import { request } from './client';

export interface ChunkDetail {
  id: string;
  source_id: string;
  page: number | null;
  heading_path: string | null;
  text: string;
  start_ms: number | null;
  end_ms: number | null;
  speaker: string | null;
}

export const sourceDetailApi = {
  getChunk: (notebookId: string, sourceId: string, chunkId: string) =>
    request<ChunkDetail>(
      `/api/notebooks/${notebookId}/sources/${sourceId}/chunks/${chunkId}`,
    ),
};

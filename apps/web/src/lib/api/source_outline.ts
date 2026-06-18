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

export interface DocumentSectionContent {
  heading_path: string | null;
  page: number | null;
  text: string;
}

export interface RecordingSegmentContent {
  ord: number;
  text: string;
  start_ms: number | null;
  end_ms: number | null;
  speaker: string | null;
}

export type SourceContent =
  | { kind: 'document'; sections: DocumentSectionContent[] }
  | { kind: 'recording'; segments: RecordingSegmentContent[] };

export const sourceDetailApi = {
  getChunk: (notebookId: string, sourceId: string, chunkId: string) =>
    request<ChunkDetail>(
      `/api/notebooks/${notebookId}/sources/${sourceId}/chunks/${chunkId}`,
    ),
  getSourceContent: (notebookId: string, sourceId: string) =>
    request<SourceContent>(
      `/api/notebooks/${notebookId}/sources/${sourceId}/content`,
    ),
};

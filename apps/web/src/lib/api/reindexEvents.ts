import type { ReindexProgress, ReindexComplete, ReindexError } from './types';

export interface ReindexHandlers {
  onProgress?: (ev: ReindexProgress) => void;
  onComplete?: (ev: ReindexComplete) => void;
  onError?: (ev: ReindexError) => void;
}

/**
 * 設定レベルの SSE(再インデックス進捗)を購読する。
 * Task7 が `GET /api/settings/events` に `reindex_progress` /
 * `reindex_complete` / `reindex_error` を配信する前提。
 * URL・イベント名が Task7 実装と異なる場合はこのファイルのみ修正する。
 * 戻り値を呼ぶと購読を閉じる。
 */
export function openReindexEvents(handlers: ReindexHandlers): () => void {
  const es = new EventSource('/api/settings/events');

  es.addEventListener('reindex_progress', (e) => {
    try {
      handlers.onProgress?.(JSON.parse((e as MessageEvent).data) as ReindexProgress);
    } catch {
      // ignore malformed payload
    }
  });
  es.addEventListener('reindex_complete', (e) => {
    try {
      handlers.onComplete?.(JSON.parse((e as MessageEvent).data) as ReindexComplete);
    } catch {
      // ignore
    }
  });
  es.addEventListener('reindex_error', (e) => {
    try {
      handlers.onError?.(JSON.parse((e as MessageEvent).data) as ReindexError);
    } catch {
      // ignore
    }
  });

  return () => es.close();
}

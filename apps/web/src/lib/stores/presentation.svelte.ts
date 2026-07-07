import { recordingsApi } from '$lib/api/recordings';
import { recordingStore } from '$lib/stores/recording.svelte';

interface Deps {
  api?: { postMarker: typeof recordingsApi.postMarker; getActive: typeof recordingsApi.getActive };
  rec?: typeof recordingStore;
}

/**
 * 発表モード(プレゼンテーション連動録音)ストア。spec: docs/specs/2026-07-06-presentation-mode-design.md §6。
 *
 * recordingStore に薄く重なる形で「発表ページ」の状態とマーカー送信を管理する。
 * マーカー送信はベストエフォート(失敗してもページ遷移そのものはUIに継続反映する)。
 */
export function createPresentationStore(deps: Deps = {}) {
  const api = deps.api ?? recordingsApi;
  const rec = deps.rec ?? recordingStore;

  let active = $state(false);
  let parentSourceId = $state<string | null>(null);
  let parentTitle = $state('');
  let page = $state(1);
  let totalPages = $state(0);
  let notebookId = '';

  function sendMarker(p: number) {
    // ベストエフォート(spec §6): 失敗してもUIは続行、次のページ送りで回復
    const rid = rec.recordingId;
    if (!rid) return;
    void api.postMarker(notebookId, rid, 'page', String(p)).catch(() => {});
  }

  function changePage(next: number) {
    const max = totalPages > 0 ? totalPages : Number.MAX_SAFE_INTEGER;
    const clamped = Math.min(Math.max(1, next), max);
    if (clamped === page) return;
    page = clamped;
    sendMarker(clamped);
  }

  return {
    get active() { return active; },
    get parentSourceId() { return parentSourceId; },
    get parentTitle() { return parentTitle; },
    get page() { return page; },
    get totalPages() { return totalPages; },

    /** SlideView が抽出済みページ数を通知する。 */
    setTotalPages(n: number) { totalPages = n; },

    async start(nbId: string, source: { id: string; title: string }) {
      notebookId = nbId;
      await rec.start(nbId, { presentationSourceId: source.id });
      parentSourceId = source.id;
      parentTitle = source.title;
      page = 1;
      totalPages = 0;
      active = true;
      sendMarker(1); // 開始と同時にページ1を記録(spec §6 開始導線)
    },

    goto(p: number) { changePage(p); },
    next() { changePage(page + 1); },
    prev() { changePage(page - 1); },

    async end() {
      await rec.stop();
      active = false;
      parentSourceId = null;
    },

    /** リロード復帰(spec §6 中断・異常系)。発表セッションが生きていれば再入。 */
    async resume(nbId: string) {
      notebookId = nbId;
      const info = await api.getActive(nbId).catch(() => undefined);
      if (!info || !info.presentation_source_id) return;
      parentSourceId = info.presentation_source_id;
      page = info.last_page ?? 1;
      active = true;
    },
  };
}

export const presentationStore = createPresentationStore();

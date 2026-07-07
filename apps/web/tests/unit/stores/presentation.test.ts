import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPresentationStore } from '$lib/stores/presentation.svelte';
import type { ActiveRecording } from '$lib/api/types';

function makeDeps() {
  const rec = {
    recordingId: 'RID',
    recording: false,
    start: vi.fn(async () => { rec.recording = true; }),
    stop: vi.fn(async () => { rec.recording = false; }),
  };
  const api = {
    postMarker: vi.fn(async () => ({ at_ms: 0 })),
    getActive: vi.fn(async (): Promise<ActiveRecording | undefined> => undefined),
  };
  return { rec, api };
}

describe('presentationStore', () => {
  let deps: ReturnType<typeof makeDeps>;
  let store: ReturnType<typeof createPresentationStore>;

  beforeEach(() => {
    deps = makeDeps();
    store = createPresentationStore({ api: deps.api, rec: deps.rec as never });
  });

  it('start で録音開始+page1マーカー送信+active化', async () => {
    await store.start('nb1', { id: 'SRC', title: '資料A' });
    expect(deps.rec.start).toHaveBeenCalledWith('nb1', { presentationSourceId: 'SRC' });
    expect(store.active).toBe(true);
    expect(store.page).toBe(1);
    expect(store.parentTitle).toBe('資料A');
    expect(deps.api.postMarker).toHaveBeenCalledWith('nb1', 'RID', 'page', '1');
  });

  it('next/prev/goto はクランプされ、変化時のみマーカー送信', async () => {
    await store.start('nb1', { id: 'SRC', title: 'A' });
    store.setTotalPages(3);
    deps.api.postMarker.mockClear();

    store.next();            // 1→2
    store.next();            // 2→3
    store.next();            // 3→3(変化なし)
    expect(store.page).toBe(3);
    expect(deps.api.postMarker).toHaveBeenCalledTimes(2);

    store.prev();            // 3→2
    store.goto(1);           // →1
    store.goto(99);          // クランプ→3
    expect(store.page).toBe(3);
    expect(deps.api.postMarker).toHaveBeenCalledTimes(5);
  });

  it('マーカー送信失敗でもページ遷移は続行する(ベストエフォート)', async () => {
    deps.api.postMarker.mockRejectedValue(new Error('down'));
    await store.start('nb1', { id: 'SRC', title: 'A' });
    store.setTotalPages(5);
    store.next();
    expect(store.page).toBe(2); // 例外がUIに伝播しない
  });

  it('end で録音停止し active 解除', async () => {
    await store.start('nb1', { id: 'SRC', title: 'A' });
    await store.end();
    expect(deps.rec.stop).toHaveBeenCalled();
    expect(store.active).toBe(false);
  });

  it('resume: 発表セッションが生きていれば復帰', async () => {
    deps.api.getActive.mockResolvedValue({
      recording_id: 'RID', source_id: 'REC',
      presentation_source_id: 'SRC', last_page: 4,
    });
    await store.resume('nb1');
    expect(store.active).toBe(true);
    expect(store.page).toBe(4);
    expect(store.parentSourceId).toBe('SRC');
  });

  it('resume: 通常録音(presentationなし)では何もしない', async () => {
    deps.api.getActive.mockResolvedValue({
      recording_id: 'RID', source_id: 'REC',
      presentation_source_id: null, last_page: null,
    });
    await store.resume('nb1');
    expect(store.active).toBe(false);
  });
});

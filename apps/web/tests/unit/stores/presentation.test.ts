import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPresentationStore } from '$lib/stores/presentation.svelte';
import type { ActiveRecording } from '$lib/api/types';

function makeDeps() {
  const rec = {
    recordingId: 'RID',
    recording: false,
    start: vi.fn(async () => { rec.recording = true; }),
    stop: vi.fn(async () => { rec.recording = false; }),
    adopt: vi.fn(() => { rec.recording = true; }),
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

  it('resume: 発表セッションが生きていれば recordingStore を先に復元して復帰', async () => {
    deps.api.getActive.mockResolvedValue({
      recording_id: 'RID', source_id: 'REC',
      presentation_source_id: 'SRC', last_page: 4, elapsed_ms: 123456,
      live_caption: true,
    });
    await store.resume('nb1');
    // recordingStore の復元(adopt)が必須: これが無いと recordingId=null のまま
    // 以降のページ送りマーカーが silently no-op になり録音コントロールも消える。
    // liveCaption はサーバーが返した実設定をそのまま渡す(ローカルトグルの推測をやめた、
    // PM-6レビュー追記)。
    expect(deps.rec.adopt).toHaveBeenCalledWith('nb1', {
      recordingId: 'RID',
      sourceId: 'REC',
      elapsedMs: 123456,
      liveCaption: true,
    });
    expect(store.active).toBe(true);
    expect(store.page).toBe(4);
    expect(store.parentSourceId).toBe('SRC');
  });

  it('resume: 通常録音(presentationなし)では何もしない', async () => {
    deps.api.getActive.mockResolvedValue({
      recording_id: 'RID', source_id: 'REC',
      presentation_source_id: null, last_page: null, elapsed_ms: 500,
      live_caption: false,
    });
    await store.resume('nb1');
    expect(store.active).toBe(false);
    expect(deps.rec.adopt).not.toHaveBeenCalled();
  });

  it('setTotalPages は確定ページ数を超えた page を再クランプする(マーカーなし)', async () => {
    await store.start('nb1', { id: 'SRC', title: 'A' });
    // totalPages 未確定(0)の間は制限なしで進める
    for (let i = 0; i < 5; i++) store.next(); // 1→6
    expect(store.page).toBe(6);

    deps.api.postMarker.mockClear();
    store.setTotalPages(3);
    expect(store.page).toBe(3);
    // 表示補正のみ: 発表者のページ移動イベントではないためマーカーは送らない
    expect(deps.api.postMarker).not.toHaveBeenCalled();
  });
});

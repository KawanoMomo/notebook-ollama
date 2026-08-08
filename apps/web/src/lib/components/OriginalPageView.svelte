<script lang="ts">
  import { fetchPageRects, pageImageUrl, type PageRect } from '$lib/api/pages';
  import { toPercentBox } from '$lib/utils/pageGeometry';

  interface Props {
    notebookId: string;
    sourceId: string;
    page: number;
    chunkId: string;
    quote: string;
  }
  let { notebookId, sourceId, page, chunkId, quote }: Props = $props();

  let current = $state(page);
  let rects = $state<PageRect[]>([]);
  let rectSource = $state<'asset' | 'quote' | 'none'>('none');
  // 矩形と同じ dpi でのページ寸法。画像の naturalWidth を使うと、画像の読み込みと
  // 矩形取得の競合で百分率がズレる(拡大直後に枠が微妙にずれる原因)。
  let pageSize = $state({ w: 0, h: 0 });
  let zoomed = $state(false);
  let wrapEl = $state<HTMLElement | null>(null);
  let pageEl = $state<HTMLElement | null>(null);
  // in-flight の古い応答が新しいページの矩形を上書きしないようにする
  // (同ファイルの utterancesFetchSeq / spanFetchSeq と同じ形)。
  let rectFetchSeq = 0;

  // 引用が変わったら、その引用のページへ戻す。
  $effect(() => {
    current = page;
  });

  // 表示中の dpi。矩形もこれと同じ dpi で取る。
  const dpi = $derived(zoomed ? 300 : 150);

  $effect(() => {
    const nb = notebookId;
    const sid = sourceId;
    const p = current;
    const cid = chunkId;
    const q = quote;
    const d = dpi;
    const seq = ++rectFetchSeq;
    rects = [];
    rectSource = 'none';
    pageSize = { w: 0, h: 0 };
    if (!sid) return;
    fetchPageRects(nb, sid, p, cid, q, d).then((r) => {
      if (seq !== rectFetchSeq) return;
      rects = r.rects;
      rectSource = r.source;
      pageSize = { w: r.page_width ?? 0, h: r.page_height ?? 0 };
    });
  });

  // 拡大したら、選択箇所が画面の中心に来るようスクロールする。
  // 「どちらへスクロールすればいいか分からない」を無くすため、探させない。
  $effect(() => {
    if (!zoomed || !wrapEl || !pageEl || rects.length === 0 || !pageSize.h) return;
    // 描画が済んでから測る
    requestAnimationFrame(() => {
      if (!wrapEl || !pageEl) return;
      const top = Math.min(...rects.map((r) => r.y));
      const bottom = Math.max(...rects.map((r) => r.y + r.h));
      const centerRatio = (top + bottom) / 2 / pageSize.h;
      const target = pageEl.offsetTop + pageEl.clientHeight * centerRatio;
      wrapEl.scrollTop = Math.max(0, target - wrapEl.clientHeight / 2);
    });
  });

  // 拡大中は Esc で閉じられるようにする。
  $effect(() => {
    if (!zoomed) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') zoomed = false;
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  function step(delta: number) {
    current = Math.max(1, current + delta);
  }

  /**
   * ホイールで前後のページへ。連続して眺めるときにボタンを狙わせない。
   * 拡大中は画像自体のスクロールが優先で、端に達してからページが変わる。
   */
  function onWheel(e: WheelEvent) {
    if (zoomed && wrapEl) {
      const atTop = wrapEl.scrollTop <= 0;
      const atBottom = wrapEl.scrollTop + wrapEl.clientHeight >= wrapEl.scrollHeight - 1;
      if (!(e.deltaY < 0 ? atTop : atBottom)) return; // まだスクロールできる
    }
    e.preventDefault();
    step(e.deltaY > 0 ? 1 : -1);
  }
</script>

<div class="wrap" class:zoomed bind:this={wrapEl} onwheel={onWheel}>
  {#if zoomed}
    <button class="close" type="button" aria-label="拡大表示を閉じる" onclick={() => (zoomed = false)}
      >✕</button
    >
  {/if}
  <div class="page" bind:this={pageEl}>
    <img
      src={pageImageUrl(notebookId, sourceId, current, dpi)}
      alt={`原本 p.${current}`}
    />
    {#each rects as r, i (i)}
      {@const box = toPercentBox(r, pageSize.w, pageSize.h)}
      <span
        class="box"
        style:left={box.left}
        style:top={box.top}
        style:width={box.width}
        style:height={box.height}
      ></span>
    {/each}
  </div>

  <div class="bar">
    <button type="button" disabled={current <= 1} onclick={() => step(-1)}>
      ◀ p.{Math.max(1, current - 1)}
    </button>
    <button type="button" onclick={() => (zoomed = !zoomed)}>{zoomed ? '縮小' : '拡大'}</button>
    <button type="button" onclick={() => step(1)}>p.{current + 1} ▶</button>
    <span class="hint">ホイールでページ送り</span>
  </div>

  {#if rectSource === 'none'}
    <p class="note">枠は特定できません(原本上で該当箇所を見つけられませんでした)</p>
  {/if}
</div>

<style>
  .wrap {
    /* ホイールをページ送りに使うので、ブラウザのスクロール連鎖を止める */
    overscroll-behavior: contain;
  }
  .page {
    position: relative;
    line-height: 0;
  }
  .page img {
    width: 100%;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
  }
  .box {
    position: absolute;
    border: 2px solid var(--color-evidence);
    background: var(--color-evidence-faint);
    border-radius: 2px;
    pointer-events: none;
  }
  .bar {
    display: flex;
    gap: var(--space-2);
    align-items: center;
    margin-top: var(--space-2);
  }
  .bar button {
    border: 1px solid var(--color-border);
    background: var(--color-bg);
    border-radius: var(--radius-sm);
    padding: 2px 8px;
    font-size: 11px;
    color: var(--color-fg);
  }
  .bar button:disabled {
    color: var(--color-fg-muted);
    cursor: default;
  }
  .hint {
    font-size: 10px;
    color: var(--color-fg-muted);
  }
  .note {
    font-size: 11px;
    color: var(--color-fg-muted);
    margin: var(--space-2) 0 0;
  }
  .close {
    position: sticky;
    top: 0;
    float: right;
    z-index: 1;
    border: 1px solid var(--color-border);
    background: var(--color-bg);
    color: var(--color-fg);
    border-radius: var(--radius-sm);
    width: 28px;
    height: 28px;
    font-size: 14px;
    line-height: 1;
    cursor: pointer;
  }
  .close:hover {
    background: var(--color-bg-elevated);
  }
  .wrap.zoomed {
    position: fixed;
    inset: 5%;
    background: var(--color-bg);
    z-index: 50;
    overflow: auto;
    padding: var(--space-4);
    border-radius: var(--radius-md);
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
  }
</style>

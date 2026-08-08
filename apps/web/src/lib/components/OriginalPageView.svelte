<script lang="ts">
  import { fetchPageRects, pageImageUrl, type PageRect } from '$lib/api/pages';
  import { toPercentBox } from '$lib/utils/pageGeometry';

  interface Props {
    notebookId: string;
    sourceId: string;
    /** 根拠のあるページ。ここへスクロールし、ここにだけ枠を出す。 */
    page: number;
    pageCount: number;
    chunkId: string;
    quote: string;
  }
  let { notebookId, sourceId, page, pageCount, chunkId, quote }: Props = $props();

  let rects = $state<PageRect[]>([]);
  let rectSource = $state<'asset' | 'quote' | 'none'>('none');
  // 矩形と同じ dpi でのページ寸法。画像の naturalWidth を使うと、画像の読み込みと
  // 矩形取得の競合で百分率がズレる。
  let pageSize = $state({ w: 0, h: 0 });
  let zoomed = $state(false);
  let scrollEl = $state<HTMLElement | null>(null);
  let visiblePage = $state(page);
  let rectFetchSeq = 0;

  const dpi = $derived(zoomed ? 300 : 150);
  const pages = $derived(Array.from({ length: Math.max(1, pageCount) }, (_, i) => i + 1));

  // 矩形は「根拠のあるページ」の分だけ取る。ページを繰るたびに探しに行くと、
  // 選択していない語まで拾ってしまううえ、スクロールが重くなる。
  $effect(() => {
    const nb = notebookId;
    const sid = sourceId;
    const p = page;
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

  /** 根拠の位置が画面の中心に来るようスクロールする(探させない)。 */
  function centerOnEvidence() {
    // each の中で bind:this は最後の要素を掴んでしまうので、印を付けて引く。
    const evidenceEl = scrollEl?.querySelector<HTMLElement>('[data-evidence="true"]');
    if (!scrollEl || !evidenceEl) return;
    const ratio =
      rects.length && pageSize.h
        ? (Math.min(...rects.map((r) => r.y)) + Math.max(...rects.map((r) => r.y + r.h))) /
          2 /
          pageSize.h
        : 0.5;
    const target = evidenceEl.offsetTop + evidenceEl.clientHeight * ratio;
    scrollEl.scrollTop = Math.max(0, target - scrollEl.clientHeight / 2);
  }

  // 引用が変わったとき / 拡大縮小したときに合わせ直す。
  $effect(() => {
    void page;
    void zoomed;
    void rects;
    requestAnimationFrame(centerOnEvidence);
  });

  $effect(() => {
    if (!zoomed) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') zoomed = false;
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  /** いま見えているページ番号を表示するだけ。判定は軽く保つ。 */
  function onScroll() {
    if (!scrollEl) return;
    const mid = scrollEl.scrollTop + scrollEl.clientHeight / 2;
    const nodes = scrollEl.querySelectorAll<HTMLElement>('[data-page]');
    for (const node of nodes) {
      if (node.offsetTop <= mid && mid < node.offsetTop + node.clientHeight) {
        visiblePage = Number(node.dataset.page);
        return;
      }
    }
  }
</script>

<div class="wrap" class:zoomed>
  <div class="controls">
    <span class="indicator">p.{visiblePage}{#if pageCount} / {pageCount}{/if}</span>
    <button type="button" onclick={centerOnEvidence} title="根拠の位置へ戻る">該当箇所</button>
    <button type="button" onclick={() => (zoomed = !zoomed)}>{zoomed ? '縮小' : '拡大'}</button>
    {#if zoomed}
      <button type="button" aria-label="拡大表示を閉じる" onclick={() => (zoomed = false)}>✕</button>
    {/if}
  </div>

  <div class="scroll" bind:this={scrollEl} onscroll={onScroll}>
    {#each pages as p (p)}
      <div class="page" data-page={p} data-evidence={p === page ? 'true' : undefined}>
        <img
          src={pageImageUrl(notebookId, sourceId, p, dpi)}
          alt={`原本 p.${p}`}
          loading="lazy"
          decoding="async"
        />
        {#if p === page}
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
        {/if}
      </div>
    {/each}
  </div>

  {#if rectSource === 'none'}
    <p class="note">枠は特定できません(原本上で該当箇所を見つけられませんでした)</p>
  {/if}
</div>

<style>
  .wrap {
    position: relative;
  }
  .controls {
    position: absolute;
    top: var(--space-2);
    right: var(--space-2);
    z-index: 2;
    display: flex;
    gap: 4px;
    align-items: center;
    background: color-mix(in srgb, var(--color-bg) 88%, transparent);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: 2px 4px;
  }
  .controls button {
    border: none;
    background: none;
    color: var(--color-fg);
    font-size: 11px;
    padding: 2px 6px;
    border-radius: var(--radius-sm);
    cursor: pointer;
  }
  .controls button:hover {
    background: var(--color-bg-elevated);
  }
  .indicator {
    font-size: 10px;
    color: var(--color-fg-muted);
    padding: 0 4px;
  }
  .scroll {
    max-height: 60vh;
    overflow: auto;
    overscroll-behavior: contain;
  }
  .page {
    position: relative;
    line-height: 0;
    margin-bottom: var(--space-2);
  }
  .page img {
    width: 100%;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-bg-elevated);
    min-height: 40px;
  }
  .box {
    position: absolute;
    border: 2px solid var(--color-evidence);
    background: var(--color-evidence-faint);
    border-radius: 2px;
    pointer-events: none;
  }
  .note {
    font-size: 11px;
    color: var(--color-fg-muted);
    margin: var(--space-2) 0 0;
  }
  .wrap.zoomed {
    position: fixed;
    inset: 5%;
    background: var(--color-bg);
    z-index: 50;
    padding: var(--space-4);
    border-radius: var(--radius-md);
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
  }
  .wrap.zoomed .scroll {
    max-height: calc(90vh - 2 * var(--space-4));
  }
</style>

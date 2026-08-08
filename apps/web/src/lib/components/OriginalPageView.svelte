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
  let natural = $state({ w: 0, h: 0 });
  let zoomed = $state(false);
  // in-flight の古い応答が新しいページの矩形を上書きしないようにする
  // (同ファイルの utterancesFetchSeq / spanFetchSeq と同じ形)。
  let rectFetchSeq = 0;

  // 引用が変わったら、その引用のページへ戻す。
  $effect(() => {
    current = page;
  });

  $effect(() => {
    const nb = notebookId;
    const sid = sourceId;
    const p = current;
    const cid = chunkId;
    const q = quote;
    const seq = ++rectFetchSeq;
    rects = [];
    rectSource = 'none';
    if (!sid) return;
    fetchPageRects(nb, sid, p, cid, q).then((r) => {
      if (seq !== rectFetchSeq) return;
      rects = r.rects;
      rectSource = r.source;
    });
  });

  function onImageLoad(e: Event) {
    const img = e.currentTarget as HTMLImageElement;
    natural = { w: img.naturalWidth, h: img.naturalHeight };
  }
</script>

<div class="wrap" class:zoomed>
  <div class="page">
    <img
      src={pageImageUrl(notebookId, sourceId, current, zoomed ? 300 : 150)}
      alt={`原本 p.${current}`}
      onload={onImageLoad}
    />
    {#each rects as r, i (i)}
      {@const box = toPercentBox(r, natural.w, natural.h)}
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
    <button type="button" disabled={current <= 1} onclick={() => (current = Math.max(1, current - 1))}>
      ◀ p.{Math.max(1, current - 1)}
    </button>
    <button type="button" onclick={() => (zoomed = !zoomed)}>{zoomed ? '縮小' : '拡大'}</button>
    <button type="button" onclick={() => (current = current + 1)}>p.{current + 1} ▶</button>
  </div>

  {#if rectSource === 'none'}
    <p class="note">枠は特定できません(原本上で該当箇所を見つけられませんでした)</p>
  {/if}
</div>

<style>
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
    overflow: auto;
    padding: var(--space-4);
    border-radius: var(--radius-md);
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
  }
</style>

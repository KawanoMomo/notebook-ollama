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

  // 表示中の dpi。矩形もこれと同じ dpi で取らないと、画像の自然サイズと
  // 矩形の座標系がズレる(拡大時に 300dpi 画像へ 150dpi の矩形を当てると半分の
  // 位置に描かれ、無関係な場所がハイライトされる)。
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
    if (!sid) return;
    fetchPageRects(nb, sid, p, cid, q, d).then((r) => {
      if (seq !== rectFetchSeq) return;
      rects = r.rects;
      rectSource = r.source;
    });
  });

  // 拡大中は Esc で閉じられるようにする(下までスクロールしないと閉じられないのは辛い)。
  $effect(() => {
    if (!zoomed) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') zoomed = false;
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  function onImageLoad(e: Event) {
    const img = e.currentTarget as HTMLImageElement;
    natural = { w: img.naturalWidth, h: img.naturalHeight };
  }
</script>

<div class="wrap" class:zoomed>
  {#if zoomed}
    <button class="close" type="button" aria-label="拡大表示を閉じる" onclick={() => (zoomed = false)}
      >✕</button
    >
  {/if}
  <div class="page">
    <img
      src={pageImageUrl(notebookId, sourceId, current, dpi)}
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

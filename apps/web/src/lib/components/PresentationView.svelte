<script lang="ts">
  import SlideView from '$lib/components/SlideView.svelte';
  import { presentationStore } from '$lib/stores/presentation.svelte';

  interface Props {
    notebookId: string;
  }
  let { notebookId }: Props = $props();

  let editingPage = $state(false);
  let pageInput = $state(1);
  let lastWheelAt = 0;
  const WHEEL_THROTTLE_MS = 150; // 300msは鈍い(既知フィードバック)

  const slidesUrl = $derived(
    `/api/notebooks/${notebookId}/sources/${presentationStore.parentSourceId}/slides`,
  );

  function onWheel(e: WheelEvent) {
    e.preventDefault(); // スライド領域上ではページ切替に専用化(字幕/ソース一覧は通常スクロール)
    const now = Date.now();
    if (now - lastWheelAt < WHEEL_THROTTLE_MS) return;
    lastWheelAt = now;
    if (e.deltaY > 0) presentationStore.next();
    else if (e.deltaY < 0) presentationStore.prev();
  }

  function startEditingPage() {
    pageInput = presentationStore.page;
    editingPage = true;
  }

  function commitPageInput() {
    presentationStore.goto(pageInput);
    editingPage = false;
  }
</script>

<!-- {#key slidesUrl} は SlideView 側のレビュー指摘どおり: ドキュメント読込失敗/URL変更は
     コンポーネント内で回復不能なため、URL(=発表対象ソース)が変わったら SlideView を
     再生成する。 -->
<div class="presentation">
  <div class="slide-area" data-testid="slide-area" onwheel={onWheel}>
    {#key slidesUrl}
      <SlideView
        url={slidesUrl}
        page={presentationStore.page}
        onTotalPages={(n) => presentationStore.setTotalPages(n)}
      />
    {/key}
  </div>
  <div class="pagebar">
    <button class="nav" aria-label="前のページ" onclick={() => presentationStore.prev()}>◀</button>
    {#if editingPage}
      <input
        class="pageinput"
        type="number"
        min="1"
        max={presentationStore.totalPages || undefined}
        bind:value={pageInput}
        onkeydown={(e) => {
          if (e.key === 'Enter') commitPageInput();
        }}
        onblur={commitPageInput}
      />
    {:else}
      <button class="pagenum" onclick={startEditingPage}>
        {presentationStore.page} / {presentationStore.totalPages}
      </button>
    {/if}
    <button class="nav" aria-label="次のページ" onclick={() => presentationStore.next()}>▶</button>
  </div>
</div>

<style>
  .presentation {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
    background: var(--color-bg);
  }
  .slide-area {
    flex: 1;
    min-height: 0;
  }
  .pagebar {
    flex: none;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-3);
    padding: var(--space-2) var(--space-4);
    border-top: 1px solid var(--color-border);
    background: var(--color-bg-elevated);
  }
  .nav {
    background: none;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    color: var(--color-fg);
    padding: var(--space-1) var(--space-2);
    line-height: 1;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .nav:hover {
    background: var(--color-bg);
    color: var(--color-accent);
  }
  .pagenum {
    background: none;
    border: none;
    color: var(--color-fg);
    font-size: 13px;
    font-family: var(--font-mono);
    padding: var(--space-1) var(--space-2);
    min-width: 64px;
    text-align: center;
  }
  .pagenum:hover {
    color: var(--color-accent);
  }
  .pageinput {
    width: 64px;
    text-align: center;
    font-size: 13px;
    font-family: var(--font-mono);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-bg);
    color: var(--color-fg);
    padding: var(--space-1) var(--space-2);
  }
</style>

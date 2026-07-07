<script lang="ts">
  import { onMount } from 'svelte';

  interface Props {
    url: string;
    page: number;
    onTotalPages?: (n: number) => void;
    onRenderError?: (msg: string) => void;
  }
  let { url, page, onTotalPages, onRenderError }: Props = $props();

  let container = $state<HTMLDivElement | null>(null);
  let canvas = $state<HTMLCanvasElement | null>(null);
  let error = $state<string | null>(null);

  // pdf.js は動的 import(SSR/prerender を確実に避ける。ルート自体も ssr=false)
  let pdfjs: typeof import('pdfjs-dist') | null = null;
  let doc: import('pdfjs-dist').PDFDocumentProxy | null = null;
  // destroy() は PDFDocumentProxy ではなく loadingTask(PDFDocumentLoadingTask)側にある
  // (pdfjs-dist v6 の API)。破棄時はこちらを呼ぶ。
  let loadingTask: import('pdfjs-dist').PDFDocumentLoadingTask | null = null;
  let renderTask: { cancel(): void } | null = null;
  let renderSeq = 0;

  onMount(() => {
    let disposed = false;
    (async () => {
      try {
        pdfjs = await import('pdfjs-dist');
        const workerUrl = (await import('pdfjs-dist/build/pdf.worker.mjs?url')).default;
        pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
        loadingTask = pdfjs.getDocument({ url });
        const loaded = await loadingTask.promise;
        if (disposed) {
          void loadingTask.destroy();
          return;
        }
        doc = loaded;
        onTotalPages?.(doc.numPages);
        await render(page);
      } catch (e) {
        error = e instanceof Error ? e.message : String(e);
        onRenderError?.(error);
      }
    })();
    const ro = new ResizeObserver(() => {
      void render(page);
    });
    if (container) ro.observe(container);
    return () => {
      disposed = true;
      ro.disconnect();
      renderTask?.cancel();
      void loadingTask?.destroy();
    };
  });

  $effect(() => {
    // page 変更で再描画(doc ロード前は onMount 側が初回描画する)
    const p = page;
    if (doc) void render(p);
  });

  async function render(p: number) {
    if (!doc || !canvas || !container) return;
    const seq = ++renderSeq;
    try {
      const pdfPage = await doc.getPage(Math.min(Math.max(1, p), doc.numPages));
      if (seq !== renderSeq) return;
      const base = pdfPage.getViewport({ scale: 1 });
      const cw = container.clientWidth;
      const ch = container.clientHeight;
      const scale = Math.min(cw / base.width, ch / base.height) * (window.devicePixelRatio || 1);
      const viewport = pdfPage.getViewport({ scale });
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      canvas.style.width = `${viewport.width / (window.devicePixelRatio || 1)}px`;
      canvas.style.height = `${viewport.height / (window.devicePixelRatio || 1)}px`;
      renderTask?.cancel();
      const task = pdfPage.render({
        canvas,
        viewport,
      });
      renderTask = task;
      await task.promise;
      error = null;
    } catch (e) {
      if (e instanceof Error && e.name === 'RenderingCancelledException') return;
      error = e instanceof Error ? e.message : String(e);
      onRenderError?.(error);
    }
  }
</script>

<div class="slide-container" bind:this={container}>
  {#if error}
    <div class="err" role="alert">スライドを表示できません: {error}</div>
  {:else}
    <canvas bind:this={canvas}></canvas>
  {/if}
</div>

<style>
  .slide-container {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    background: var(--color-bg);
  }
  .err {
    color: var(--color-fg-muted);
    font-size: 13px;
    padding: var(--space-4);
  }
</style>

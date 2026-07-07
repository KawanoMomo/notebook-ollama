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
  // unmount 後に in-flight の async 処理(ロード/描画)が state 更新や
  // onRenderError 通知を行わないためのフラグ。render() もこれを見る。
  let disposed = false;

  onMount(() => {
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
        if (disposed) return;
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
    if (disposed || !doc || !canvas || !container) return;
    const seq = ++renderSeq;
    try {
      const pdfPage = await doc.getPage(Math.min(Math.max(1, p), doc.numPages));
      if (disposed || seq !== renderSeq) return;
      const base = pdfPage.getViewport({ scale: 1 });
      const cw = container.clientWidth;
      const ch = container.clientHeight;
      // レイアウト未確定(非表示・初期マウント直後など)で 0 の間は描画しない。
      // scale が Infinity/NaN になるのを防ぐ。サイズ確定時に ResizeObserver が再描画する。
      if (cw <= 0 || ch <= 0) return;
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

<!-- canvas は常に DOM に残す(hidden で隠すだけ)。{#if} で外すと bind:this が
     null に戻り、以後の render() が全てガードで止まって一時的な失敗から回復
     できなくなる。エラーはオーバーレイ表示し、次の render 成功で error=null →
     canvas が再表示されて自然回復する。 -->
<div class="slide-container" bind:this={container}>
  <canvas bind:this={canvas} class:hidden={error !== null}></canvas>
  {#if error}
    <div class="err" role="alert">スライドを表示できません: {error}</div>
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
  .hidden {
    display: none;
  }
  .err {
    color: var(--color-fg-muted);
    font-size: 13px;
    padding: var(--space-4);
  }
</style>

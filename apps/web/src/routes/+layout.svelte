<script lang="ts">
  import '../app.css';
  import { onMount, onDestroy } from 'svelte';
  import AppHeader from '$lib/components/AppHeader.svelte';
  import Toast from '$lib/components/Toast.svelte';
  import NotebookSwitcher from '$lib/components/NotebookSwitcher.svelte';
  import FeedbackHubDrawer from '$lib/components/FeedbackHubDrawer.svelte';
  import CrashDetectionModal from '$lib/components/CrashDetectionModal.svelte';
  import CrashPreviewDialog from '$lib/components/CrashPreviewDialog.svelte';
  import { bindShortcuts } from '$lib/utils/keys';
  import { initErrorBoundary } from '$lib/utils/errorBoundary';
  import { afterNavigate } from '$app/navigation';
  import { navMemoryStore } from '$lib/stores/navMemory.svelte';
  import { feedbackHubStore } from '$lib/stores/feedbackHub.svelte';
  import { crashReportsStore } from '$lib/stores/crashReports.svelte';

  let { children } = $props();
  let switcherOpen = $state(false);
  let unbindShortcuts: (() => void) | null = null;
  // initErrorBoundary returns its own unbind; we keep them separate so HMR /
  // teardown can clean each up independently (and so a regression in one
  // can't silently leak listeners from the other).
  let unbindErrorBoundary: (() => void) | null = null;

  onMount(() => {
    unbindShortcuts = bindShortcuts([
      {
        combo: 'Mod+k',
        handler: () => (switcherOpen = true),
      },
    ]);
    // Wire frontend crash auto-detection (Sprint 5 Task 5.8). Without this
    // call, `window.error` / `unhandledrejection` go nowhere and the entire
    // CrashDetectionModal pipeline is dark in production.
    unbindErrorBoundary = initErrorBoundary();
  });
  onDestroy(() => {
    unbindShortcuts?.();
    unbindErrorBoundary?.();
  });

  // 各遷移完了時に「設定以外」の現在パスを記録し、設定からの戻り先にする。
  afterNavigate((nav) => {
    const path = nav.to?.url.pathname;
    if (path) navMemoryStore.record(path);
  });
</script>

<AppHeader />
<main>
  {@render children()}
</main>
<Toast />

{#if switcherOpen}
  <NotebookSwitcher onClose={() => (switcherOpen = false)} />
{/if}

{#if feedbackHubStore.drawerOpen}
  <FeedbackHubDrawer />
{/if}

{#if crashReportsStore.activeImmediate}
  {@const activeCrash = crashReportsStore.activeImmediate}
  <CrashDetectionModal
    crash={activeCrash}
    onDismiss={() => crashReportsStore.clearImmediate()}
    onPreview={(crash) => {
      // §5.6 → §5.7 ハンドオフ: 即時モーダルを閉じ、previewing スロットに
      // 同じクラッシュをセットして CrashPreviewDialog をマウントする。
      crashReportsStore.showPreview(crash);
      crashReportsStore.clearImmediate();
    }}
  />
{/if}

{#if crashReportsStore.previewing}
  {@const previewCrash = crashReportsStore.previewing}
  <CrashPreviewDialog
    crash={previewCrash}
    onClose={() => crashReportsStore.clearPreview()}
    onDismissed={() => crashReportsStore.clearPreview()}
    onReported={() => crashReportsStore.clearPreview()}
  />
{/if}

<style>
  main {
    min-height: calc(100vh - var(--header-height));
  }
</style>

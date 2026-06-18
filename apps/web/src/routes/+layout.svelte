<script lang="ts">
  import '../app.css';
  import { onMount, onDestroy } from 'svelte';
  import AppHeader from '$lib/components/AppHeader.svelte';
  import Toast from '$lib/components/Toast.svelte';
  import NotebookSwitcher from '$lib/components/NotebookSwitcher.svelte';
  import { bindShortcuts } from '$lib/utils/keys';
  import { afterNavigate } from '$app/navigation';
  import { navMemoryStore } from '$lib/stores/navMemory.svelte';

  let { children } = $props();
  let switcherOpen = $state(false);
  let unbind: (() => void) | null = null;

  onMount(() => {
    unbind = bindShortcuts([
      {
        combo: 'Mod+k',
        handler: () => (switcherOpen = true),
      },
    ]);
  });
  onDestroy(() => unbind?.());

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

<style>
  main {
    min-height: calc(100vh - var(--header-height));
  }
</style>

<script lang="ts">
  import '../app.css';
  import { onMount, onDestroy } from 'svelte';
  import AppHeader from '$lib/components/AppHeader.svelte';
  import Toast from '$lib/components/Toast.svelte';
  import NotebookSwitcher from '$lib/components/NotebookSwitcher.svelte';
  import { bindShortcuts } from '$lib/utils/keys';

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

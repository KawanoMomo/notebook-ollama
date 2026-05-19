<script lang="ts">
  import { onMount } from 'svelte';
  import { notebooksStore } from '$lib/stores/notebooks.svelte';
  import NotebookCard from '$lib/components/NotebookCard.svelte';
  import NotebookCreateModal from '$lib/components/NotebookCreateModal.svelte';
  import Button from '$lib/components/Button.svelte';
  import Spinner from '$lib/components/Spinner.svelte';
  import { goto } from '$app/navigation';
  import { Plus } from '@lucide/svelte';

  let showCreate = $state(false);

  onMount(() => {
    notebooksStore.load();
  });
</script>

<div class="container">
  <div class="header">
    <h1>ノートブック</h1>
    <Button onclick={() => (showCreate = true)}>
      <Plus size={16} /> 新規ノートブック
    </Button>
  </div>

  {#if notebooksStore.loading}
    <div class="state"><Spinner /> 読み込み中…</div>
  {:else if notebooksStore.error}
    <div class="state err">エラー: {notebooksStore.error}</div>
  {:else if notebooksStore.items.length === 0}
    <div class="state">
      ノートブックがありません。「新規ノートブック」で作成してください。
    </div>
  {:else}
    <div class="grid">
      {#each notebooksStore.items as nb (nb.id)}
        <NotebookCard notebook={nb} />
      {/each}
    </div>
  {/if}
</div>

{#if showCreate}
  <NotebookCreateModal
    onClose={() => (showCreate = false)}
    onCreated={(nb) => {
      notebooksStore.add(nb);
      showCreate = false;
      goto(`/notebooks/${nb.id}`);
    }}
  />
{/if}

<style>
  .container {
    max-width: 1200px;
    margin: 0 auto;
    padding: var(--space-5);
  }
  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--space-5);
  }
  h1 {
    margin: 0;
    font-size: 22px;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: var(--space-4);
  }
  .state {
    padding: var(--space-7) 0;
    text-align: center;
    color: var(--color-fg-muted);
  }
  .err {
    color: var(--color-error);
  }
</style>

<script lang="ts">
  import Modal from './Modal.svelte';
  import { goto } from '$app/navigation';
  import { notebooksStore } from '$lib/stores/notebooks.svelte';
  import { onMount } from 'svelte';

  interface Props {
    onClose: () => void;
  }
  let { onClose }: Props = $props();
  let q = $state('');

  onMount(() => {
    if (notebooksStore.items.length === 0) notebooksStore.load();
  });

  let filtered = $derived(
    notebooksStore.items.filter((nb) =>
      q.trim() ? nb.name.toLowerCase().includes(q.toLowerCase()) : true,
    ),
  );

  function pick(id: string) {
    onClose();
    goto(`/notebooks/${id}`);
  }
</script>

<Modal title="ノートブックを切り替え" {onClose}>
  <input
    type="search"
    bind:value={q}
    placeholder="名前で絞り込み"
    autofocus
    class="search"
  />
  <ul>
    {#each filtered as nb (nb.id)}
      <li>
        <button onclick={() => pick(nb.id)}>
          <strong>{nb.name}</strong>
          <span>{nb.source_count} sources</span>
        </button>
      </li>
    {/each}
    {#if filtered.length === 0}
      <li class="empty">該当なし</li>
    {/if}
  </ul>
</Modal>

<style>
  .search {
    width: 100%;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-2) var(--space-3);
    margin-bottom: var(--space-3);
  }
  ul {
    margin: 0;
    padding: 0;
    list-style: none;
    max-height: 360px;
    overflow-y: auto;
  }
  li button {
    width: 100%;
    text-align: left;
    background: none;
    border: none;
    padding: var(--space-3);
    border-radius: var(--radius-md);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  li button:hover {
    background: var(--color-bg-elevated);
  }
  li button span {
    font-size: 12px;
    color: var(--color-fg-muted);
  }
  .empty {
    padding: var(--space-3);
    color: var(--color-fg-muted);
    text-align: center;
  }
</style>

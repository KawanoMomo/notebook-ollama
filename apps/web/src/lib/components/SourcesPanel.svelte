<script lang="ts">
  import { Plus } from '@lucide/svelte';
  import SourceCard from './SourceCard.svelte';
  import SourceUploadModal from './SourceUploadModal.svelte';
  import Button from './Button.svelte';
  import { currentNotebookStore } from '$lib/stores/currentNotebook.svelte';
  import { sourcesApi } from '$lib/api/sources';
  import { pushToast } from './Toast.svelte';
  import type { Source } from '$lib/api/types';

  interface Props {
    notebookId: string;
    onSourceSelect: (id: string) => void;
  }
  let { notebookId, onSourceSelect }: Props = $props();

  let showUpload = $state(false);
  let filter = $state('');

  let filteredSources = $derived(
    currentNotebookStore.sources.filter((s) =>
      filter.trim()
        ? (s.title ?? s.origin ?? '').toLowerCase().includes(filter.toLowerCase())
        : true,
    ),
  );

  async function onRetry(s: Source) {
    try {
      const updated = await sourcesApi.retry(notebookId, s.id);
      currentNotebookStore.upsertSource(updated);
      pushToast('再試行を開始しました', 'info');
    } catch (e) {
      pushToast(e instanceof Error ? e.message : String(e), 'error');
    }
  }

  async function onDelete(s: Source) {
    if (!confirm(`「${s.title ?? s.origin}」を削除しますか？`)) return;
    try {
      await sourcesApi.delete(notebookId, s.id);
      currentNotebookStore.removeSource(s.id);
      pushToast('削除しました', 'success');
    } catch (e) {
      pushToast(e instanceof Error ? e.message : String(e), 'error');
    }
  }
</script>

<div class="panel">
  <div class="header">
    <input
      class="search"
      type="search"
      bind:value={filter}
      placeholder="ソースを検索"
    />
    <Button size="sm" onclick={() => (showUpload = true)}>
      <Plus size="14" /> 追加
    </Button>
  </div>
  <div class="list">
    {#each filteredSources as s (s.id)}
      <SourceCard
        source={s}
        selected={currentNotebookStore.selectedSourceIds.has(s.id)}
        onToggle={() => currentNotebookStore.toggleSelected(s.id)}
        onSelect={() => onSourceSelect(s.id)}
        onRetry={() => onRetry(s)}
        onDelete={() => onDelete(s)}
      />
    {/each}
    {#if filteredSources.length === 0}
      <p class="empty">ソースがありません。「追加」から取り込んでください。</p>
    {/if}
  </div>
</div>

{#if showUpload}
  <SourceUploadModal
    {notebookId}
    onClose={() => (showUpload = false)}
    onUploaded={(s) => currentNotebookStore.upsertSource(s)}
  />
{/if}

<style>
  .panel {
    display: flex;
    flex-direction: column;
    height: 100%;
  }
  .header {
    display: flex;
    gap: var(--space-2);
    padding: var(--space-3);
    border-bottom: 1px solid var(--color-border);
    background: var(--color-bg);
  }
  .search {
    flex: 1;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-1) var(--space-2);
    font-size: 13px;
  }
  .list {
    flex: 1;
    overflow-y: auto;
  }
  .empty {
    padding: var(--space-5);
    color: var(--color-fg-muted);
    text-align: center;
    font-size: 13px;
  }
</style>

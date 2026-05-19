<script lang="ts">
  import { sourceDetailApi, type ChunkDetail } from '$lib/api/source_outline';
  import { currentNotebookStore } from '$lib/stores/currentNotebook.svelte';
  import { conversationStore } from '$lib/stores/conversation.svelte';
  import Spinner from './Spinner.svelte';
  import { formatBytes } from '$lib/utils/format';

  interface Props {
    notebookId: string;
    selectedChunkId: string | null;
    selectedSourceId: string | null;
  }
  let { notebookId, selectedChunkId, selectedSourceId }: Props = $props();

  let chunk = $state<ChunkDetail | null>(null);
  let loading = $state(false);
  let error = $state<string | null>(null);

  // Resolve source for the chunk (look up in latest assistant message's citations)
  let resolvedSourceId = $derived.by(() => {
    if (selectedSourceId) return selectedSourceId;
    if (!selectedChunkId) return null;
    const latest = [...conversationStore.messages]
      .reverse()
      .find((m) => m.role === 'assistant');
    return latest?.citations.find((c) => c.chunk_id === selectedChunkId)?.source_id ?? null;
  });

  $effect(() => {
    const cid = selectedChunkId;
    const sid = resolvedSourceId;
    if (!cid || !sid) {
      chunk = null;
      return;
    }
    loading = true;
    error = null;
    sourceDetailApi
      .getChunk(notebookId, sid, cid)
      .then((c) => {
        chunk = c;
      })
      .catch((e) => {
        error = e instanceof Error ? e.message : String(e);
      })
      .finally(() => {
        loading = false;
      });
  });

  let sourceMeta = $derived(
    resolvedSourceId
      ? currentNotebookStore.sources.find((s) => s.id === resolvedSourceId)
      : null,
  );
</script>

<div class="viewer">
  {#if sourceMeta}
    <header>
      <h3>{sourceMeta.title ?? sourceMeta.origin ?? '無題'}</h3>
      <div class="meta">
        <span>{sourceMeta.kind}</span>
        {#if sourceMeta.page_count}<span>{sourceMeta.page_count}p</span>{/if}
        {#if sourceMeta.bytes}<span>{formatBytes(sourceMeta.bytes)}</span>{/if}
      </div>
    </header>
  {:else}
    <p class="empty">ソースまたは引用を選択してください</p>
  {/if}

  {#if loading}
    <div class="state"><Spinner /> 読み込み中…</div>
  {:else if error}
    <div class="state err">エラー: {error}</div>
  {:else if chunk}
    <div class="chunk">
      {#if chunk.heading_path}
        <div class="path">{chunk.heading_path}</div>
      {/if}
      {#if chunk.page}
        <div class="page">p.{chunk.page}</div>
      {/if}
      <pre class="text">{chunk.text}</pre>
    </div>
  {/if}
</div>

<style>
  .viewer {
    padding: var(--space-3);
    height: 100%;
    overflow-y: auto;
  }
  header h3 {
    margin: 0 0 var(--space-2);
    font-size: 14px;
  }
  .meta {
    display: flex;
    gap: var(--space-2);
    font-size: 12px;
    color: var(--color-fg-muted);
    margin-bottom: var(--space-3);
  }
  .meta span {
    background: var(--color-bg-elevated);
    padding: 1px var(--space-2);
    border-radius: var(--radius-sm);
  }
  .empty,
  .state {
    color: var(--color-fg-muted);
    text-align: center;
    padding: var(--space-5);
    font-size: 13px;
  }
  .err {
    color: var(--color-error);
  }
  .chunk {
    border-top: 1px solid var(--color-border);
    padding-top: var(--space-3);
  }
  .path {
    font-size: 12px;
    color: var(--color-fg-muted);
    margin-bottom: var(--space-1);
  }
  .page {
    font-size: 11px;
    color: var(--color-fg-muted);
    margin-bottom: var(--space-2);
  }
  .text {
    background: var(--color-citation-bg);
    border-left: 3px solid var(--color-citation-border);
    padding: var(--space-3);
    border-radius: var(--radius-sm);
    white-space: pre-wrap;
    font-family: inherit;
    font-size: 13px;
    line-height: 1.6;
    margin: 0;
  }
</style>

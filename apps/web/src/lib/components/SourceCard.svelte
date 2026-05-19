<script lang="ts">
  import type { Source } from '$lib/api/types';
  import { FileText, Globe, CheckCircle, AlertCircle, RefreshCw, Trash2 } from '@lucide/svelte';
  import Spinner from './Spinner.svelte';

  interface Props {
    source: Source;
    selected: boolean;
    onToggle: () => void;
    onSelect: () => void;
    onRetry: () => void;
    onDelete: () => void;
  }
  let { source, selected, onToggle, onSelect, onRetry, onDelete }: Props = $props();

  const KIND_ICON: Record<string, typeof FileText> = {
    pdf: FileText,
    markdown: FileText,
    txt: FileText,
    docx: FileText,
    pptx: FileText,
    xlsx: FileText,
    web: Globe,
  };
</script>

<div class="card" class:err={source.status === 'error'}>
  <input
    type="checkbox"
    checked={selected}
    onchange={onToggle}
    aria-label="このソースをクエリ対象に含める"
  />
  <button class="body" onclick={onSelect}>
    <div class="row">
      {#if (KIND_ICON[source.kind] ?? FileText)}
        {@const Icon = KIND_ICON[source.kind] ?? FileText}
        <Icon size="14" />
      {/if}
      <span class="title">{source.title ?? source.origin ?? '無題'}</span>
    </div>
    <div class="meta">
      <span class="kind">{source.kind}</span>
      {#if source.page_count}<span>{source.page_count}p</span>{/if}
      <span class="status">
        {#if source.status === 'ready'}
          <CheckCircle size="12" color="var(--color-success)" /> ready
        {:else if source.status === 'error'}
          <AlertCircle size="12" color="var(--color-error)" /> {source.error_msg ?? 'error'}
        {:else}
          <Spinner size={12} /> {source.status}
        {/if}
      </span>
    </div>
  </button>
  <div class="actions">
    {#if source.status === 'error'}
      <button class="icon" onclick={onRetry} aria-label="再試行">
        <RefreshCw size="14" />
      </button>
    {/if}
    <button class="icon danger" onclick={onDelete} aria-label="削除">
      <Trash2 size="14" />
    </button>
  </div>
</div>

<style>
  .card {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border-bottom: 1px solid var(--color-border);
  }
  .card.err {
    background: rgba(211, 47, 47, 0.04);
  }
  .body {
    background: none;
    border: none;
    text-align: left;
    padding: 0;
    overflow: hidden;
  }
  .row {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .title {
    font-size: 13px;
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .meta {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: 11px;
    color: var(--color-fg-muted);
    margin-top: var(--space-1);
  }
  .kind {
    background: var(--color-bg-elevated);
    padding: 1px var(--space-2);
    border-radius: var(--radius-sm);
    text-transform: uppercase;
    font-size: 10px;
  }
  .status {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
  }
  .actions {
    display: flex;
    gap: var(--space-1);
  }
  .icon {
    background: none;
    border: none;
    color: var(--color-fg-muted);
    padding: var(--space-1);
    border-radius: var(--radius-sm);
    display: inline-flex;
  }
  .icon:hover {
    background: var(--color-bg-elevated);
    color: var(--color-fg);
  }
  .icon.danger:hover {
    color: var(--color-error);
  }
</style>

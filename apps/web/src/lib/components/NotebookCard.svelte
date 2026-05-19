<script lang="ts">
  import type { Notebook } from '$lib/api/types';
  import { formatRelativeTime } from '$lib/utils/format';
  import { FileText } from '@lucide/svelte';

  interface Props {
    notebook: Notebook;
  }
  let { notebook }: Props = $props();
</script>

<a class="card" href={`/notebooks/${notebook.id}`}>
  <h3>{notebook.name}</h3>
  {#if notebook.description}
    <p class="desc">{notebook.description}</p>
  {/if}
  <div class="meta">
    <span class="count">
      <FileText size={14} />
      {notebook.source_count} ソース
    </span>
    {#if notebook.default_model}
      <span class="model">{notebook.default_model}</span>
    {/if}
    <span class="time">更新 {formatRelativeTime(notebook.updated_at)}</span>
  </div>
</a>

<style>
  .card {
    display: block;
    background: var(--color-bg-elevated);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: var(--space-4);
    text-decoration: none;
    color: var(--color-fg);
    transition: border-color 0.12s, box-shadow 0.12s;
  }
  .card:hover {
    border-color: var(--color-accent);
    box-shadow: 0 4px 12px rgba(53, 99, 233, 0.08);
    text-decoration: none;
  }
  h3 {
    margin: 0 0 var(--space-2);
    font-size: 16px;
  }
  .desc {
    margin: 0 0 var(--space-3);
    color: var(--color-fg-muted);
    font-size: 13px;
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .meta {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3);
    font-size: 12px;
    color: var(--color-fg-muted);
  }
  .meta .count {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
  }
  .model {
    background: var(--color-bg-sidebar);
    padding: 2px var(--space-2);
    border-radius: var(--radius-sm);
    font-family: var(--font-mono);
    font-size: 11px;
  }
</style>

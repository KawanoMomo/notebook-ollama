<script lang="ts">
  import { Megaphone, Settings } from '@lucide/svelte';
  import { feedbackHubStore } from '$lib/stores/feedbackHub.svelte';
  interface Props {
    title?: string;
    children?: import('svelte').Snippet;
  }
  let { title = 'Notebook Ollama', children }: Props = $props();
</script>

<header>
  <a href="/" class="brand">
    {title}
  </a>
  <div class="actions">
    {#if children}
      {@render children()}
    {/if}
    <button
      type="button"
      class="icon-btn megaphone-btn"
      aria-label="お知らせ・フィードバック"
      title="お知らせ・フィードバック"
      onclick={() => feedbackHubStore.open()}
    >
      <Megaphone size={18} strokeWidth={1.75} />
      {#if feedbackHubStore.unreadCount > 0}
        <span class="badge-dot" aria-label="未読あり"></span>
      {/if}
    </button>
    <a href="/settings" class="icon-btn" aria-label="設定">
      <Settings size={18} />
    </a>
  </div>
</header>

<style>
  header {
    height: var(--header-height);
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 var(--space-5);
    border-bottom: 1px solid var(--color-border);
    background: var(--color-bg);
    position: sticky;
    top: 0;
    z-index: 50;
  }
  .brand {
    font-weight: 600;
    color: var(--color-fg);
    text-decoration: none;
  }
  .actions {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }
  .icon-btn {
    color: var(--color-fg-muted);
    display: inline-flex;
    padding: var(--space-2);
    border-radius: var(--radius-md);
    background: transparent;
    border: 0;
    cursor: pointer;
  }
  .icon-btn:hover {
    background: var(--color-bg-elevated);
  }
  .megaphone-btn {
    position: relative;
  }
  .badge-dot {
    position: absolute;
    top: 4px;
    right: 4px;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #ef4444;
    box-shadow: 0 0 0 1.5px var(--color-bg);
    pointer-events: none;
  }
</style>

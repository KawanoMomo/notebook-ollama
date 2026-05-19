<script lang="ts">
  import { Settings } from '@lucide/svelte';
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
  }
  .icon-btn:hover {
    background: var(--color-bg-elevated);
  }
</style>

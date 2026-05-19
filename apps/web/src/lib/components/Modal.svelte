<script lang="ts">
  import { X } from '@lucide/svelte';
  interface Props {
    title: string;
    onClose: () => void;
    children: import('svelte').Snippet;
  }
  let { title, onClose, children }: Props = $props();

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') onClose();
  }
</script>

<svelte:window onkeydown={onKey} />

<div class="backdrop" onclick={onClose} role="presentation">
  <div class="dialog" role="dialog" aria-modal="true" aria-label={title} onclick={(e) => e.stopPropagation()}>
    <header>
      <h2>{title}</h2>
      <button class="close" aria-label="閉じる" onclick={onClose}>
        <X size={18} />
      </button>
    </header>
    <div class="body">
      {@render children()}
    </div>
  </div>
</div>

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.4);
    display: flex;
    justify-content: center;
    align-items: center;
    z-index: 100;
  }
  .dialog {
    background: var(--color-bg);
    border-radius: var(--radius-lg);
    min-width: 400px;
    max-width: 90vw;
    max-height: 90vh;
    display: flex;
    flex-direction: column;
    box-shadow: 0 20px 40px rgba(0, 0, 0, 0.2);
  }
  header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--space-4);
    border-bottom: 1px solid var(--color-border);
  }
  header h2 {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
  }
  .close {
    background: none;
    border: none;
    color: var(--color-fg-muted);
    padding: var(--space-1);
    border-radius: var(--radius-sm);
  }
  .close:hover {
    background: var(--color-bg-elevated);
  }
  .body {
    padding: var(--space-4);
    overflow: auto;
  }
</style>

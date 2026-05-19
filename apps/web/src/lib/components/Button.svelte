<script lang="ts">
  interface Props {
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
    size?: 'sm' | 'md';
    disabled?: boolean;
    type?: 'button' | 'submit';
    onclick?: (e: MouseEvent) => void;
    children: import('svelte').Snippet;
  }
  let {
    variant = 'primary',
    size = 'md',
    disabled = false,
    type = 'button',
    onclick,
    children,
  }: Props = $props();
</script>

<button class={`btn ${variant} ${size}`} {disabled} {type} {onclick}>
  {@render children()}
</button>

<style>
  .btn {
    border: 1px solid transparent;
    border-radius: var(--radius-md);
    padding: var(--space-2) var(--space-4);
    font-weight: 500;
    transition: background-color 0.12s, border-color 0.12s, color 0.12s;
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
  }
  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .sm {
    padding: var(--space-1) var(--space-3);
    font-size: 13px;
  }
  .primary {
    background: var(--color-accent);
    color: white;
  }
  .primary:hover:not(:disabled) {
    background: var(--color-accent-hover);
  }
  .secondary {
    background: var(--color-bg-elevated);
    color: var(--color-fg);
    border-color: var(--color-border);
  }
  .secondary:hover:not(:disabled) {
    background: var(--color-bg-sidebar);
  }
  .ghost {
    background: transparent;
    color: var(--color-fg);
  }
  .ghost:hover:not(:disabled) {
    background: var(--color-bg-elevated);
  }
  .danger {
    background: var(--color-error);
    color: white;
  }
</style>

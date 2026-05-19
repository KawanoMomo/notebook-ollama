<script lang="ts" module>
  type ToastLevel = 'info' | 'success' | 'error';
  interface ToastItem {
    id: number;
    level: ToastLevel;
    message: string;
  }
  let toasts = $state<ToastItem[]>([]);
  let nextId = 1;

  export function pushToast(message: string, level: ToastLevel = 'info', duration = 3000) {
    const id = nextId++;
    toasts = [...toasts, { id, level, message }];
    setTimeout(() => {
      toasts = toasts.filter((t) => t.id !== id);
    }, duration);
  }
</script>

<div class="container" aria-live="polite">
  {#each toasts as t (t.id)}
    <div class={`toast ${t.level}`}>{t.message}</div>
  {/each}
</div>

<style>
  .container {
    position: fixed;
    bottom: var(--space-5);
    right: var(--space-5);
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    z-index: 200;
  }
  .toast {
    background: var(--color-fg);
    color: white;
    padding: var(--space-3) var(--space-4);
    border-radius: var(--radius-md);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
    min-width: 200px;
  }
  .success {
    background: var(--color-success);
  }
  .error {
    background: var(--color-error);
  }
</style>

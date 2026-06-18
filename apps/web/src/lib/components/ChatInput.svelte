<script lang="ts">
  import Button from './Button.svelte';
  import { Send, Square } from '@lucide/svelte';

  interface Props {
    streaming: boolean;
    hint?: string | null;
    onSend: (text: string) => void;
    onCancel: () => void;
  }
  let { streaming, hint = null, onSend, onCancel }: Props = $props();

  let value = $state('');

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      submit();
    }
  }

  function submit() {
    if (streaming) return;
    const t = value.trim();
    if (!t) return;
    onSend(t);
    value = '';
  }
</script>

<form class="input" onsubmit={(e) => { e.preventDefault(); submit(); }}>
  <textarea
    bind:value
    placeholder="質問を入力（Cmd/Ctrl+Enter で送信）"
    rows="3"
    onkeydown={onKey}
  ></textarea>
  <div class="row">
    <span class="hint">{hint ?? ''}</span>
    {#if streaming}
      <Button type="button" variant="danger" onclick={onCancel}>
        <Square size={14} /> 停止
      </Button>
    {:else}
      <Button type="submit">
        <Send size={14} /> 送信
      </Button>
    {/if}
  </div>
</form>

<style>
  .input {
    padding: var(--space-3);
    border-top: 1px solid var(--color-border);
    background: var(--color-bg);
  }
  textarea {
    width: 100%;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-2) var(--space-3);
    resize: vertical;
    min-height: 60px;
    font-size: 14px;
  }
  textarea:focus {
    outline: none;
    border-color: var(--color-accent);
  }
  .row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: var(--space-2);
  }
  .hint {
    font-size: 11px;
    color: var(--color-fg-muted);
  }
</style>

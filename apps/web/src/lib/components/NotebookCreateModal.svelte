<script lang="ts">
  import Modal from './Modal.svelte';
  import Button from './Button.svelte';
  import { notebooksApi } from '$lib/api/notebooks';
  import type { Notebook } from '$lib/api/types';

  interface Props {
    onClose: () => void;
    onCreated: (nb: Notebook) => void;
  }
  let { onClose, onCreated }: Props = $props();

  let name = $state('');
  let description = $state('');
  let submitting = $state(false);
  let errMsg = $state<string | null>(null);

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    submitting = true;
    errMsg = null;
    try {
      const nb = await notebooksApi.create({
        name: name.trim(),
        description: description.trim() || undefined,
      });
      onCreated(nb);
    } catch (e) {
      errMsg = e instanceof Error ? e.message : String(e);
    } finally {
      submitting = false;
    }
  }
</script>

<Modal title="新規ノートブック" {onClose}>
  <form onsubmit={submit}>
    <label>
      <span>名前</span>
      <input
        id="nb-name"
        type="text"
        bind:value={name}
        required
        maxlength="200"
        autofocus
        aria-label="名前"
      />
    </label>
    <label>
      <span>説明（任意）</span>
      <textarea bind:value={description} rows="3"></textarea>
    </label>
    {#if errMsg}
      <p class="err">{errMsg}</p>
    {/if}
    <div class="actions">
      <Button variant="secondary" onclick={onClose}>キャンセル</Button>
      <Button type="submit" disabled={submitting || !name.trim()}>
        {submitting ? '作成中…' : '作成'}
      </Button>
    </div>
  </form>
</Modal>

<style>
  form {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    min-width: 400px;
  }
  label {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  label span {
    font-size: 12px;
    color: var(--color-fg-muted);
  }
  input,
  textarea {
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-2) var(--space-3);
    font-size: 14px;
  }
  input:focus,
  textarea:focus {
    outline: none;
    border-color: var(--color-accent);
  }
  .err {
    color: var(--color-error);
    margin: 0;
    font-size: 13px;
  }
  .actions {
    display: flex;
    gap: var(--space-2);
    justify-content: flex-end;
    margin-top: var(--space-2);
  }
</style>

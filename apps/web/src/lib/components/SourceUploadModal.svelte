<script lang="ts">
  import Modal from './Modal.svelte';
  import Button from './Button.svelte';
  import { sourcesApi } from '$lib/api/sources';
  import { pushToast } from './Toast.svelte';
  import type { Source } from '$lib/api/types';

  interface Props {
    notebookId: string;
    onClose: () => void;
    onUploaded: (s: Source) => void;
  }
  let { notebookId, onClose, onUploaded }: Props = $props();

  type Tab = 'file' | 'url';
  let tab = $state<Tab>('file');
  let files = $state<File[]>([]);
  let url = $state('');
  let submitting = $state(false);
  let errMsg = $state<string | null>(null);

  function onFileChange(e: Event) {
    const input = e.target as HTMLInputElement;
    files = Array.from(input.files ?? []);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    if (e.dataTransfer?.files) {
      files = Array.from(e.dataTransfer.files);
    }
  }

  async function submit() {
    if (tab === 'file' && files.length === 0) return;
    if (tab === 'url' && !url.trim()) return;
    submitting = true;
    errMsg = null;
    try {
      if (tab === 'file') {
        for (const f of files) {
          const s = await sourcesApi.uploadFile(notebookId, f);
          onUploaded(s);
        }
        pushToast(`${files.length} 件アップロード完了`, 'success');
      } else {
        const s = await sourcesApi.uploadUrl(notebookId, url.trim());
        onUploaded(s);
        pushToast('URL を取り込みキューに追加しました', 'success');
      }
      onClose();
    } catch (e) {
      errMsg = e instanceof Error ? e.message : String(e);
    } finally {
      submitting = false;
    }
  }
</script>

<Modal title="ソース追加" {onClose}>
  <div class="tabs">
    <button class:active={tab === 'file'} onclick={() => (tab = 'file')}>ファイル</button>
    <button class:active={tab === 'url'} onclick={() => (tab = 'url')}>URL</button>
  </div>

  {#if tab === 'file'}
    <div
      class="dropzone"
      ondragover={(e) => e.preventDefault()}
      ondrop={onDrop}
      role="presentation"
    >
      <p>ファイルを選択またはドラッグ&ドロップ</p>
      <p class="hint">PDF / MD / TXT / DOCX / PPTX / XLSX</p>
      <input
        type="file"
        multiple
        accept=".pdf,.md,.markdown,.txt,.docx,.pptx,.xlsx"
        onchange={onFileChange}
      />
      {#if files.length > 0}
        <ul class="files">
          {#each files as f}
            <li>{f.name}</li>
          {/each}
        </ul>
      {/if}
    </div>
  {:else}
    <label class="urlinput">
      <span>URL</span>
      <input type="url" bind:value={url} placeholder="https://example.com/article" />
    </label>
  {/if}

  {#if errMsg}
    <p class="err">{errMsg}</p>
  {/if}

  <div class="actions">
    <Button variant="secondary" onclick={onClose}>キャンセル</Button>
    <Button
      onclick={submit}
      disabled={submitting || (tab === 'file' ? files.length === 0 : !url.trim())}
    >
      {submitting ? 'アップロード中…' : '追加'}
    </Button>
  </div>
</Modal>

<style>
  .tabs {
    display: flex;
    gap: var(--space-3);
    margin-bottom: var(--space-4);
    border-bottom: 1px solid var(--color-border);
  }
  .tabs button {
    background: none;
    border: none;
    padding: var(--space-2) var(--space-3);
    color: var(--color-fg-muted);
    border-bottom: 2px solid transparent;
  }
  .tabs button.active {
    color: var(--color-fg);
    border-bottom-color: var(--color-accent);
  }
  .dropzone {
    border: 2px dashed var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-5);
    text-align: center;
  }
  .dropzone p {
    margin: 0 0 var(--space-2);
  }
  .hint {
    color: var(--color-fg-muted);
    font-size: 12px;
  }
  .files {
    list-style: none;
    margin: var(--space-3) 0 0;
    padding: 0;
    font-size: 13px;
    text-align: left;
  }
  .urlinput {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .urlinput span {
    font-size: 12px;
    color: var(--color-fg-muted);
  }
  .urlinput input {
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-2) var(--space-3);
  }
  .err {
    color: var(--color-error);
    font-size: 13px;
    margin: var(--space-3) 0 0;
  }
  .actions {
    display: flex;
    gap: var(--space-2);
    justify-content: flex-end;
    margin-top: var(--space-4);
  }
</style>

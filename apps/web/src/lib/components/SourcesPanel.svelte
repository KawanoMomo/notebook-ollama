<script lang="ts">
  import { Plus, Mic } from '@lucide/svelte';
  import SourceCard from './SourceCard.svelte';
  import SourceUploadModal from './SourceUploadModal.svelte';
  import RecordingControls from './RecordingControls.svelte';
  import Button from './Button.svelte';
  import { currentNotebookStore } from '$lib/stores/currentNotebook.svelte';
  import { recordingStore } from '$lib/stores/recording.svelte';
  import { sourcesApi } from '$lib/api/sources';
  import { pushToast } from './Toast.svelte';
  import type { Source } from '$lib/api/types';

  interface Props {
    notebookId: string;
    onSourceSelect: (id: string) => void;
  }
  let { notebookId, onSourceSelect }: Props = $props();

  let showUpload = $state(false);
  let filter = $state('');
  let dragDepth = $state(0);
  let uploading = $state(false);

  const SUPPORTED_EXTS = ['.pdf', '.md', '.markdown', '.txt', '.docx', '.pptx', '.xlsx'];

  let filteredSources = $derived(
    currentNotebookStore.sources.filter((s) =>
      filter.trim()
        ? (s.title ?? s.origin ?? '').toLowerCase().includes(filter.toLowerCase())
        : true,
    ),
  );

  function isSupported(name: string): boolean {
    const n = name.toLowerCase();
    return SUPPORTED_EXTS.some((ext) => n.endsWith(ext));
  }

  async function uploadFiles(list: File[]) {
    if (list.length === 0) return;
    uploading = true;
    let ok = 0;
    try {
      for (const f of list) {
        if (!isSupported(f.name)) {
          pushToast(`未対応のファイル形式: ${f.name}`, 'error');
          continue;
        }
        try {
          const s = await sourcesApi.uploadFile(notebookId, f);
          currentNotebookStore.upsertSource(s);
          ok++;
        } catch (e) {
          pushToast(
            `${f.name}: ${e instanceof Error ? e.message : String(e)}`,
            'error',
          );
        }
      }
      if (ok > 0) pushToast(`${ok} 件アップロード完了`, 'success');
    } finally {
      uploading = false;
    }
  }

  function onDragEnter(e: DragEvent) {
    if (!e.dataTransfer?.types.includes('Files')) return;
    e.preventDefault();
    dragDepth++;
  }
  function onDragOver(e: DragEvent) {
    if (!e.dataTransfer?.types.includes('Files')) return;
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
  }
  function onDragLeave(e: DragEvent) {
    if (!e.dataTransfer?.types.includes('Files')) return;
    e.preventDefault();
    dragDepth = Math.max(0, dragDepth - 1);
  }
  async function onDrop(e: DragEvent) {
    if (!e.dataTransfer?.types.includes('Files')) return;
    e.preventDefault();
    dragDepth = 0;
    const list = Array.from(e.dataTransfer?.files ?? []);
    await uploadFiles(list);
  }

  async function onReembed(s: Source) {
    try {
      await sourcesApi.recordingRetry(notebookId, s.id);
      // retry は {source_id,status} を返すため Source 全体を取り直して反映する。
      const fresh = await sourcesApi.list(notebookId);
      const updated = fresh.find((x) => x.id === s.id);
      if (updated) currentNotebookStore.upsertSource(updated);
      pushToast('再生成を開始しました', 'info');
    } catch (e) {
      pushToast(e instanceof Error ? e.message : String(e), 'error');
    }
  }

  async function onStopConversion(s: Source) {
    // 進行中の録音変換を停止。BE は即座に error("変換を停止しました") へ落とすので、
    // 最新 Source を取り直してカードに反映する(SSE でも追従するが即時性のため)。
    try {
      await sourcesApi.cancelConversion(notebookId, s.id);
      const fresh = await sourcesApi.list(notebookId);
      const updated = fresh.find((x) => x.id === s.id);
      if (updated) currentNotebookStore.upsertSource(updated);
      pushToast('変換を停止しました', 'info');
    } catch (e) {
      pushToast(e instanceof Error ? e.message : String(e), 'error');
    }
  }

  async function onRetry(s: Source) {
    if (s.kind === 'recording') {
      await onReembed(s);
      return;
    }
    try {
      const updated = await sourcesApi.retry(notebookId, s.id);
      currentNotebookStore.upsertSource(updated);
      pushToast('再試行を開始しました', 'info');
    } catch (e) {
      pushToast(e instanceof Error ? e.message : String(e), 'error');
    }
  }

  async function startRecording() {
    if (recordingStore.recording) return;
    try {
      await recordingStore.start(notebookId);
    } catch (e) {
      pushToast(e instanceof Error ? e.message : String(e), 'error');
    }
  }

  async function onDelete(s: Source) {
    if (!confirm(`「${s.title ?? s.origin}」を削除しますか？`)) return;
    try {
      await sourcesApi.delete(notebookId, s.id);
      currentNotebookStore.removeSource(s.id);
      pushToast('削除しました', 'success');
    } catch (e) {
      pushToast(e instanceof Error ? e.message : String(e), 'error');
    }
  }

  async function onRename(s: Source, title: string) {
    try {
      const updated = await sourcesApi.rename(notebookId, s.id, title);
      currentNotebookStore.upsertSource(updated);
      pushToast('名前を変更しました', 'success');
    } catch (e) {
      pushToast(e instanceof Error ? e.message : String(e), 'error');
    }
  }
</script>

<div
  class="panel"
  class:dragover={dragDepth > 0}
  ondragenter={onDragEnter}
  ondragover={onDragOver}
  ondragleave={onDragLeave}
  ondrop={onDrop}
  role="presentation"
>
  <div class="header">
    <input
      class="search"
      type="search"
      bind:value={filter}
      placeholder="ソースを検索"
    />
    <Button size="sm" onclick={() => (showUpload = true)}>
      <Plus size="14" /> 追加
    </Button>
    <button
      class="rec-icon"
      class:active={recordingStore.recording}
      title="録音"
      aria-label="録音"
      onclick={startRecording}
      disabled={recordingStore.recording}
    >
      <Mic size="16" />
    </button>
  </div>
  <RecordingControls {notebookId} />
  <div class="list">
    {#each filteredSources as s (s.id)}
      <SourceCard
        source={s}
        selected={currentNotebookStore.selectedSourceIds.has(s.id)}
        onToggle={() => currentNotebookStore.toggleSelected(s.id)}
        onSelect={() => onSourceSelect(s.id)}
        onRetry={() => onRetry(s)}
        onReembed={() => onReembed(s)}
        onStopConversion={() => onStopConversion(s)}
        onDelete={() => onDelete(s)}
        onRename={(id, title) => onRename(s, title)}
      />
    {/each}
    {#if filteredSources.length === 0}
      <p class="empty">ソースがありません。「追加」から取り込むか、ファイルをここにドラッグ&ドロップしてください。</p>
    {/if}
  </div>
  {#if dragDepth > 0}
    <div class="drop-overlay">
      <div class="drop-msg">
        {uploading ? 'アップロード中…' : 'ドロップで追加'}
        <p class="drop-hint">PDF / MD / TXT / DOCX / PPTX / XLSX</p>
      </div>
    </div>
  {/if}
</div>

{#if showUpload}
  <SourceUploadModal
    {notebookId}
    onClose={() => (showUpload = false)}
    onUploaded={(s) => currentNotebookStore.upsertSource(s)}
  />
{/if}

<style>
  .panel {
    display: flex;
    flex-direction: column;
    height: 100%;
    position: relative;
  }
  .panel.dragover {
    outline: 2px dashed var(--color-accent);
    outline-offset: -4px;
  }
  .drop-overlay {
    position: absolute;
    inset: 0;
    background: color-mix(in srgb, var(--color-accent) 8%, transparent);
    display: flex;
    align-items: center;
    justify-content: center;
    pointer-events: none;
    z-index: 10;
  }
  .drop-msg {
    background: var(--color-bg);
    border: 1px solid var(--color-accent);
    border-radius: var(--radius-md);
    padding: var(--space-4) var(--space-5);
    text-align: center;
    color: var(--color-fg);
    font-weight: 500;
  }
  .drop-hint {
    margin: var(--space-2) 0 0;
    font-size: 12px;
    color: var(--color-fg-muted);
    font-weight: 400;
  }
  .header {
    display: flex;
    gap: var(--space-2);
    padding: var(--space-3);
    border-bottom: 1px solid var(--color-border);
    background: var(--color-bg);
  }
  .search {
    flex: 1;
    min-width: 0;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-1) var(--space-2);
    font-size: 13px;
  }
  .rec-icon {
    flex: none;
    width: 30px;
    height: 30px;
    border-radius: var(--radius-md);
    border: 1px solid var(--color-border);
    background: var(--color-bg);
    color: var(--color-error);
    display: grid;
    place-items: center;
    transition: background-color 0.12s, border-color 0.12s;
  }
  .rec-icon:hover:not(:disabled) {
    background: #fff5f5;
    border-color: #f0c4c4;
  }
  .rec-icon.active {
    background: #fff5f5;
    border-color: #f0c4c4;
  }
  .rec-icon:disabled {
    cursor: default;
  }
  .list {
    flex: 1;
    overflow-y: auto;
  }
  .empty {
    padding: var(--space-5);
    color: var(--color-fg-muted);
    text-align: center;
    font-size: 13px;
  }
</style>

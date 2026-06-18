<script lang="ts">
  import type { Source } from '$lib/api/types';
  import { FileText, Globe, Mic, CheckCircle, AlertCircle, RefreshCw, Trash2, Pencil } from '@lucide/svelte';
  import Spinner from './Spinner.svelte';
  import RecordingConvStatus from './RecordingConvStatus.svelte';

  interface Props {
    source: Source;
    selected: boolean;
    onToggle: () => void;
    onSelect: () => void;
    onRetry: () => void;
    onReembed: () => void;
    onDelete: () => void;
    // optional にして CR.4 単独でも SourcesPanel の callsite が型エラーにならないようにする
    // (CR.5 で実ハンドラを配線する)。
    onRename?: (id: string, title: string) => void;
  }
  let { source, selected, onToggle, onSelect, onRetry, onReembed, onDelete, onRename }: Props = $props();

  const KIND_ICON: Record<string, typeof FileText> = {
    pdf: FileText,
    markdown: FileText,
    txt: FileText,
    docx: FileText,
    pptx: FileText,
    xlsx: FileText,
    web: Globe,
    recording: Mic,
  };

  function formatDuration(ms: number): string {
    const totalSec = Math.floor(ms / 1000);
    const mm = Math.floor(totalSec / 60);
    const ss = totalSec % 60;
    return `${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`;
  }

  const durationLabel = $derived(
    typeof source.duration_ms === 'number' && source.duration_ms > 0
      ? formatDuration(source.duration_ms)
      : null,
  );

  // Recording sources that are still being converted (not ready / not error) get the
  // detailed step panel rendered below the card body.
  const showConvStatus = $derived(
    source.kind === 'recording' &&
      source.status !== 'ready' &&
      source.status !== 'error',
  );

  // 録音の再生成(再埋め込み)可否: 録音 && 0チャンクで ready && 音源あり。
  // error 録音は既存 retry ボタン(status==='error' で表示)が担い、Step 5 で
  // 録音時のみ recordingRetry へルーティングする。二重ボタンを避けるため
  // canReembed は error を含めず「0チャンク ready」だけを拾う。
  const canReembed = $derived(
    source.kind === 'recording' &&
      (source.chunk_count ?? 0) === 0 &&
      source.status === 'ready' &&
      source.has_audio === true,
  );

  // インライン題名編集。鉛筆クリックで editing=true、Enter/blur で確定、Esc で取消。
  // 確定値が空 or 変更なしなら API を呼ばない (no-op)。
  let editing = $state(false);
  let editValue = $state('');

  const currentTitle = $derived(source.title ?? source.origin ?? '無題');

  function startEdit(e: MouseEvent) {
    e.stopPropagation();
    editValue = source.title ?? '';
    editing = true;
  }

  function commitEdit() {
    if (!editing) return;
    editing = false;
    const next = editValue.trim();
    if (!next || next === (source.title ?? '')) return;
    onRename?.(source.id, next);
  }

  function cancelEdit() {
    editing = false;
  }

  function onEditKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault();
      commitEdit();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cancelEdit();
    }
  }
</script>

<div class="card-wrap" class:converting={showConvStatus}>
<div class="card" class:err={source.status === 'error'}>
  <input
    type="checkbox"
    checked={selected}
    onchange={onToggle}
    aria-label="このソースをクエリ対象に含める"
  />
  <div class="body-wrap">
    <div class="row">
      {#if (KIND_ICON[source.kind] ?? FileText)}
        {@const Icon = KIND_ICON[source.kind] ?? FileText}
        <Icon size="14" />
      {/if}
      {#if editing}
        <!-- svelte-ignore a11y_autofocus -->
        <input
          class="title-edit"
          type="text"
          bind:value={editValue}
          onkeydown={onEditKeydown}
          onblur={commitEdit}
          onclick={(e) => e.stopPropagation()}
          autofocus
          aria-label="ソース名を編集"
        />
      {:else}
        <button class="title-btn" onclick={onSelect}>
          <span class="title">{currentTitle}</span>
        </button>
        <button
          class="icon edit"
          onclick={startEdit}
          aria-label="名前を編集"
          title="名前を編集"
        >
          <Pencil size="12" />
        </button>
      {/if}
    </div>
    <button class="meta-btn" onclick={onSelect}>
      <div class="meta">
        <span class="kind">{source.kind}</span>
        {#if source.page_count}<span>{source.page_count}p</span>{/if}
        {#if durationLabel}<span>{durationLabel}</span>{/if}
        <span class="status">
          {#if source.status === 'ready'}
            <CheckCircle size="12" color="var(--color-success)" /> ready
          {:else if source.status === 'error'}
            <AlertCircle size="12" color="var(--color-error)" /> {source.error_msg ?? 'error'}
          {:else if source.status === 'embedding' && source.chunk_count}
            <Spinner size={12} /> embedding ({source.embedded ?? 0}/{source.chunk_count})
          {:else}
            <Spinner size={12} /> {source.status}
          {/if}
        </span>
      </div>
    </button>
  </div>
  <div class="actions">
    {#if source.status === 'error'}
      <button class="icon" onclick={onRetry} aria-label="再試行">
        <RefreshCw size="14" />
      </button>
    {/if}
    {#if canReembed}
      <button class="icon" onclick={onReembed} aria-label="再生成" title="再生成">
        <RefreshCw size="14" />
      </button>
    {/if}
    <button class="icon danger" onclick={onDelete} aria-label="削除">
      <Trash2 size="14" />
    </button>
  </div>
</div>
{#if showConvStatus}
  <RecordingConvStatus sourceId={source.id} />
{/if}
</div>

<style>
  .card-wrap.converting > .card {
    border-bottom: none;
  }
  .card {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border-bottom: 1px solid var(--color-border);
  }
  .card.err {
    background: rgba(211, 47, 47, 0.04);
  }
  .body-wrap {
    min-width: 0;
    overflow: hidden;
  }
  .title-btn,
  .meta-btn {
    background: none;
    border: none;
    text-align: left;
    padding: 0;
    overflow: hidden;
    display: block;
    width: 100%;
    cursor: pointer;
  }
  .title-btn {
    min-width: 0;
    flex: 1;
  }
  .title-edit {
    flex: 1;
    min-width: 0;
    font-size: 13px;
    font-weight: 500;
    border: 1px solid var(--color-accent);
    border-radius: var(--radius-sm);
    padding: 1px var(--space-1);
  }
  .icon.edit {
    opacity: 0;
    flex: none;
  }
  .card:hover .icon.edit {
    opacity: 1;
  }
  .row {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .title {
    font-size: 13px;
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .meta {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: 11px;
    color: var(--color-fg-muted);
    margin-top: var(--space-1);
  }
  .kind {
    background: var(--color-bg-elevated);
    padding: 1px var(--space-2);
    border-radius: var(--radius-sm);
    text-transform: uppercase;
    font-size: 10px;
  }
  .status {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
  }
  .actions {
    display: flex;
    gap: var(--space-1);
  }
  .icon {
    background: none;
    border: none;
    color: var(--color-fg-muted);
    padding: var(--space-1);
    border-radius: var(--radius-sm);
    display: inline-flex;
  }
  .icon:hover {
    background: var(--color-bg-elevated);
    color: var(--color-fg);
  }
  .icon.danger:hover {
    color: var(--color-error);
  }
</style>

<script lang="ts">
  import { Plus, Mic, Check, Minus } from '@lucide/svelte';
  import SourceCard from './SourceCard.svelte';
  import SourceUploadModal from './SourceUploadModal.svelte';
  import ParentPickerModal from './ParentPickerModal.svelte';
  import RecordingControls from './RecordingControls.svelte';
  import Button from './Button.svelte';
  import Spinner from './Spinner.svelte';
  import { currentNotebookStore } from '$lib/stores/currentNotebook.svelte';
  import { recordingStore } from '$lib/stores/recording.svelte';
  import { presentationStore } from '$lib/stores/presentation.svelte';
  import { sourcesApi } from '$lib/api/sources';
  import { pushToast } from './Toast.svelte';
  import { computeBulkState } from './SourcesPanel.bulk';
  import { orderWithChildren } from '$lib/utils/sourceTree';
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

  // 検索フィルタ入力中(query 非空)はツリー無効=フラット表示(depth 全て 0)。
  // 未入力時のみ親子ツリー順に並べ替える。
  let rows = $derived(
    filter.trim()
      ? filteredSources.map((s) => ({ source: s, depth: 0 as const }))
      : orderWithChildren(filteredSources, currentNotebookStore.links),
  );

  // 仕様 §2.2: フィルタ中は表示中ソースのみを対象にしたトライステート/カウントを出す。
  const bulk = $derived(
    computeBulkState({
      visibleIds: filteredSources.map((s) => s.id),
      selectedIds: currentNotebookStore.selectedSourceIds,
    }),
  );

  function onBulkToggle() {
    if (bulk.state === 'none') {
      // 全選択(フィルタ中なら表示中ソースだけ)
      currentNotebookStore.selectAll(filteredSources.map((s) => s.id));
    } else {
      // 全/一部選択 → 全解除(表示中ソースだけ)
      const visible = new Set(filteredSources.map((s) => s.id));
      // 表示外のソースの選択状態は保持する: 一度全部消してから、表示外で
      // 元々選択されていたものだけ復元する。
      const survivors = Array.from(currentNotebookStore.selectedSourceIds).filter(
        (id) => !visible.has(id),
      );
      currentNotebookStore.clearSelection();
      if (survivors.length > 0) currentNotebookStore.selectAll(survivors);
    }
  }

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
    // クリック受付の即時フィードバック: API 応答を待たず parsing 表示へ切り替え、
    // 変換ステータスパネルと停止ボタンを即座に出す(気付けない問題への対処)。
    currentNotebookStore.upsertSource({ ...s, status: 'parsing' });
    pushToast('変換を開始しました', 'info');
    try {
      await sourcesApi.recordingRetry(notebookId, s.id);
      // retry は {source_id,status} を返すため Source 全体を取り直して反映する。
      const fresh = await sourcesApi.list(notebookId);
      const updated = fresh.find((x) => x.id === s.id);
      if (updated) currentNotebookStore.upsertSource(updated);
    } catch (e) {
      // 失敗(409: 既に実行中 等)は実状態へ巻き戻してからエラー表示
      const fresh = await sourcesApi.list(notebookId).catch(() => null);
      const updated = fresh?.find((x) => x.id === s.id);
      if (updated) currentNotebookStore.upsertSource(updated);
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

  // ガイド開閉状態。クリックで開閉、ソース選択時に自動展開(§4.1)。
  let guideOpen = $state<Set<string>>(new Set());

  function toggleGuide(id: string) {
    const next = new Set(guideOpen);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    guideOpen = next;
  }

  function toggleGuideAndSelect(s: Source) {
    // タイトルクリック = ガイドの開閉トグル + 右パネルの原文表示。
    // 既存 ▶ キャレットでの開閉と挙動を統一する(2回目クリックで閉じる)。
    // 右パネル表示は閉じても維持する(別ソースに切り替えるときだけ変わる)。
    toggleGuide(s.id);
    onSourceSelect(s.id);
  }

  async function onSummarize(s: Source) {
    try {
      const updated = await sourcesApi.summarize(notebookId, s.id);
      currentNotebookStore.upsertSource(updated);
      pushToast('要約を再生成しています', 'info');
    } catch (e) {
      pushToast(e instanceof Error ? e.message : String(e), 'error');
    }
  }

  async function onSummaryCancel(s: Source) {
    try {
      const updated = await sourcesApi.cancelSummary(notebookId, s.id);
      currentNotebookStore.upsertSource(updated);
      pushToast('要約を中断しました', 'info');
    } catch (e) {
      pushToast(e instanceof Error ? e.message : String(e), 'error');
    }
  }

  async function onGenerateAdr(s: Source) {
    try {
      const updated = await sourcesApi.generateAdr(notebookId, s.id);
      currentNotebookStore.upsertSource(updated);
      // ADR は決定があれば ready、無ければ skipped。toast は中立に。
      pushToast('ADR 抽出を開始しました', 'info');
      // ガイドも自動で開く(結果が見えるように)
      if (!guideOpen.has(s.id)) {
        guideOpen = new Set([...guideOpen, s.id]);
      }
    } catch (e) {
      pushToast(e instanceof Error ? e.message : String(e), 'error');
    }
  }

  async function onStartPresentation(s: Source) {
    // 録音競合(409)や recording extra 未導入(503)は ApiError.message が
    // そのまま利用者への適切な案内になる(バックエンド側で文言を作り込み済み)。
    try {
      await presentationStore.start(notebookId, { id: s.id, title: s.title ?? '' });
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

  // 親ソース設定モーダル。開いている対象(子)を保持する(null なら閉じている)。
  let parentPickerFor = $state<Source | null>(null);

  // id を起点に、リンクを辿った子孫(直接の子だけでなく多段も)の ID 集合を返す。
  // ParentPickerModal の候補から「自身と自身の子孫」を除外するために使う。
  function descendantIdsOf(id: string): Set<string> {
    const childrenMap = new Map<string, string[]>();
    for (const l of currentNotebookStore.links) {
      const arr = childrenMap.get(l.parent_source_id) ?? [];
      arr.push(l.child_source_id);
      childrenMap.set(l.parent_source_id, arr);
    }
    const result = new Set<string>();
    const stack = [id];
    const visited = new Set<string>([id]);
    while (stack.length > 0) {
      const cur = stack.pop() as string;
      for (const c of childrenMap.get(cur) ?? []) {
        if (visited.has(c)) continue;
        visited.add(c);
        result.add(c);
        stack.push(c);
      }
    }
    return result;
  }

  let parentPickerCandidates = $derived.by(() => {
    const child = parentPickerFor;
    if (!child) return [];
    const excluded = descendantIdsOf(child.id);
    excluded.add(child.id);
    return currentNotebookStore.sources.filter((s) => !excluded.has(s.id));
  });

  function openParentPicker(s: Source) {
    parentPickerFor = s;
  }

  function closeParentPicker() {
    parentPickerFor = null;
  }

  async function pickParent(parentId: string) {
    const child = parentPickerFor;
    closeParentPicker();
    if (!child) return;
    try {
      await currentNotebookStore.setParent(child.id, parentId);
      pushToast('親ソースを設定しました', 'success');
    } catch (e) {
      pushToast(e instanceof Error ? e.message : String(e), 'error');
    }
  }

  function hasParent(id: string): boolean {
    return currentNotebookStore.links.some((l) => l.child_source_id === id);
  }

  async function onRemoveParent(s: Source) {
    try {
      await currentNotebookStore.removeParent(s.id);
      pushToast('リンクを解除しました', 'success');
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
      aria-busy={recordingStore.starting}
      onclick={startRecording}
      disabled={recordingStore.recording || recordingStore.starting}
    >
      {#if recordingStore.starting}
        <Spinner size={16} />
      {:else}
        <Mic size="16" />
      {/if}
    </button>
  </div>
  <RecordingControls {notebookId} />
  <button
    class="bulk-row"
    data-state={bulk.state}
    onclick={onBulkToggle}
    aria-label="すべてのソースを選択切替"
  >
    <span class="bulk-box" data-state={bulk.state}>
      {#if bulk.state === 'all'}
        <Check size="11" color="#fff" strokeWidth={3} />
      {:else if bulk.state === 'some'}
        <Minus size="11" color="#fff" strokeWidth={3} />
      {/if}
    </span>
    <span class="bulk-label">すべてのソース</span>
    <span class="bulk-count">{bulk.label}</span>
  </button>
  <div class="list">
    {#each rows as row (row.source.id)}
      {@const s = row.source}
      <SourceCard
        source={s}
        depth={row.depth}
        selected={currentNotebookStore.selectedSourceIds.has(s.id)}
        onToggle={() => currentNotebookStore.toggleSelected(s.id)}
        onSelect={() => toggleGuideAndSelect(s)}
        onRetry={() => onRetry(s)}
        onReembed={() => onReembed(s)}
        onStopConversion={() => onStopConversion(s)}
        onDelete={() => onDelete(s)}
        onRename={(id, title) => onRename(s, title)}
        guideExpanded={guideOpen.has(s.id)}
        onGuideToggle={() => toggleGuide(s.id)}
        onSummarize={() => onSummarize(s)}
        onSummaryCancel={() => onSummaryCancel(s)}
        onGenerateAdr={() => onGenerateAdr(s)}
        onStartPresentation={() => onStartPresentation(s)}
        onSetParent={() => openParentPicker(s)}
        onRemoveParent={hasParent(s.id) ? () => onRemoveParent(s) : undefined}
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

{#if parentPickerFor}
  <ParentPickerModal
    candidates={parentPickerCandidates}
    onPick={pickParent}
    onClose={closeParentPicker}
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
  .bulk-row {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    width: 100%;
    padding: var(--space-2) var(--space-3);
    background: var(--color-bg);
    border: none;
    border-bottom: 1px solid var(--color-border);
    cursor: pointer;
    font-size: 12px;
    text-align: left;
  }
  .bulk-row:hover {
    background: var(--color-bg-elevated);
  }
  .bulk-box {
    width: 14px;
    height: 14px;
    border-radius: 3px;
    border: 1.5px solid var(--color-border);
    display: grid;
    place-items: center;
    flex: none;
  }
  .bulk-box[data-state='all'],
  .bulk-box[data-state='some'] {
    background: var(--color-accent);
    border-color: var(--color-accent);
  }
  .bulk-label {
    flex: 1;
    color: var(--color-fg);
    font-weight: 500;
  }
  .bulk-count {
    color: var(--color-fg-muted);
    font-variant-numeric: tabular-nums;
  }
</style>

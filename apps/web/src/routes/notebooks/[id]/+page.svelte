<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { ArrowLeft } from '@lucide/svelte';
  import { currentNotebookStore } from '$lib/stores/currentNotebook.svelte';
  import { modelsStore } from '$lib/stores/models.svelte';
  import { settingsStore } from '$lib/stores/settings.svelte';
  import { conversationStore } from '$lib/stores/conversation.svelte';
  import { eventsStore } from '$lib/stores/events.svelte';
  import { pushToast } from '$lib/components/Toast.svelte';
  import { bindShortcuts } from '$lib/utils/keys';
  import Spinner from '$lib/components/Spinner.svelte';
  import JobStatusBar from '$lib/components/JobStatusBar.svelte';
  import SourcesPanel from '$lib/components/SourcesPanel.svelte';
  import ChatPanel from '$lib/components/ChatPanel.svelte';
  import LiveCaptionView from '$lib/components/LiveCaptionView.svelte';
  import PresentationView from '$lib/components/PresentationView.svelte';
  import SourceViewer from '$lib/components/SourceViewer.svelte';
  import { recordingStore } from '$lib/stores/recording.svelte';
  import { presentationStore } from '$lib/stores/presentation.svelte';

  let { data } = $props<{ data: { notebookId: string } }>();

  let viewerOpen = $state(true);
  let selectedSourceId = $state<string | null>(null);
  let selectedChunkId = $state<string | null>(null);
  let unbindShortcuts: (() => void) | null = null;

  // 全体既定名(設定未ロード時は空文字)
  const globalDefault = $derived(settingsStore.settings?.ollama.default_model ?? '');
  // チャット可能モデルのみ(kind が chat / both)
  const chatModels = $derived(
    modelsStore.models.filter((m) => m.kind === 'chat' || m.kind === 'both'),
  );
  // <select> の現在値。null(=既定)は空文字 '' を選択。
  const selectedModel = $derived(currentNotebookStore.notebook?.default_model ?? '');

  // 進行中ジョブに録音変換パイプラインの step 情報(あれば)を合成する。
  // summary/adr ジョブは step を発行しないため ingest のみ対象。
  const jobRows = $derived(
    currentNotebookStore.activeJobs.map((j) => ({
      ...j,
      step: j.kind === 'ingest' ? eventsStore.convStepFor(j.sourceId) : undefined,
    })),
  );

  async function onModelChange(e: Event) {
    const value = (e.currentTarget as HTMLSelectElement).value;
    const next: string | null = value === '' ? null : value;
    const prev = currentNotebookStore.notebook?.default_model ?? null;
    if (next === prev) return;
    try {
      await currentNotebookStore.update({ default_model: next });
      pushToast(
        next === null
          ? `このノートのモデルを既定（${globalDefault}）に戻しました`
          : `このノートのモデルを ${next} に変更しました`,
        'success',
      );
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), 'error');
    }
  }

  // when notebook changes, reset conversation and restore this notebook's latest
  // conversation from BE (2026-07-05 実機FB: 前ノートの履歴が残って見えた)。
  $effect(() => {
    const nb = data.notebookId;
    // Singleton store is shared across pages — clear it, then reload for this notebook.
    conversationStore.reset();
    void conversationStore.loadLatest(nb);
  });

  // Prevent browser default (opening PDFs/text in a new tab) when files are
  // dropped outside the SourcesPanel dropzone.
  function blockFileDrop(e: DragEvent) {
    if (e.dataTransfer?.types.includes('Files')) e.preventDefault();
  }

  onMount(async () => {
    window.addEventListener('dragover', blockFileDrop);
    window.addEventListener('drop', blockFileDrop);
    await currentNotebookStore.load(data.notebookId);
    // モデルピッカー用: モデル一覧と全体既定名を取得(失敗してもページは描画継続)
    void modelsStore.load();
    void settingsStore.load();
    eventsStore.start(data.notebookId);
    // リロード復帰(spec §6): 発表セッションが生きていれば発表ビューへ再入する。
    void presentationStore.resume(data.notebookId);
    unbindShortcuts = bindShortcuts([
      {
        combo: 'Mod+/',
        allowInInput: true,
        handler: () => {
          const ta = document.querySelector<HTMLTextAreaElement>('main textarea');
          ta?.focus();
        },
      },
      {
        combo: 'Mod+b',
        handler: () => (viewerOpen = !viewerOpen),
      },
      {
        combo: 'ArrowRight',
        // enabled: 発表中でなければ matches() 判定自体を行わない(preventDefault も
        // 発火しない)。ハンドラ内 return だけだと、フォーカス中のボタン等への
        // 既定キー動作(Space でのクリック等)を発表外でも握り潰してしまうため。
        enabled: () => presentationStore.active,
        handler: () => presentationStore.next(),
      },
      {
        combo: 'ArrowLeft',
        enabled: () => presentationStore.active,
        handler: () => presentationStore.prev(),
      },
      {
        combo: 'Space',
        enabled: () => presentationStore.active,
        handler: () => presentationStore.next(),
      },
    ]);
  });

  onDestroy(() => {
    window.removeEventListener('dragover', blockFileDrop);
    window.removeEventListener('drop', blockFileDrop);
    eventsStore.stop();
    currentNotebookStore.clear();
    unbindShortcuts?.();
  });
</script>

<div class="detail">
  <div class="topbar">
    <button class="back" onclick={() => goto('/')} aria-label="戻る">
      <ArrowLeft size="16" />
    </button>
    <h2>{currentNotebookStore.notebook?.name ?? '読み込み中…'}</h2>
      {#if currentNotebookStore.notebook}
        <label class="model-pick">
          <span class="model-pick-label">このノートのモデル</span>
          <select value={selectedModel} onchange={onModelChange}>
            <option value="">既定（{globalDefault || '全体既定'}）</option>
            {#each chatModels as m (m.name)}
              <option value={m.name}>{m.name}</option>
            {/each}
          </select>
        </label>
      {/if}
    </div>

  <JobStatusBar jobs={jobRows} />

  {#if currentNotebookStore.loading}
    <div class="state"><Spinner /> 読み込み中…</div>
  {:else if currentNotebookStore.error}
    <div class="state err">エラー: {currentNotebookStore.error}</div>
  {:else}
    <div class="cols" class:viewer-open={viewerOpen || presentationStore.active}>
      <aside class="sources">
        <SourcesPanel
          notebookId={data.notebookId}
          onSourceSelect={(id) => {
            // ソース選択と引用選択は排他。引用の選択を消さないと、
            // SourceViewer が古い selectedSourceId を優先してしまう。
            selectedSourceId = id;
            selectedChunkId = null;
          }}
        />
      </aside>
      <section class="chat">
        {#if presentationStore.active}
          <PresentationView notebookId={data.notebookId} />
        {:else if recordingStore.recording}
          <LiveCaptionView />
        {:else}
          <ChatPanel
            notebookId={data.notebookId}
            onCitationClick={(cid, sourceId) => {
              if (cid.startsWith('vp:')) {
                // 視覚インデックス由来の合成チャンク(vp:<source_id>:<page>)は
                // BE 側に実チャンク行が無く getChunk が失敗するため、
                // 通常のソース選択(全文ビュー)へフォールバックする。
                selectedSourceId = sourceId;
                selectedChunkId = null;
                return;
              }
              // 引用クリック時は古いソース選択を消し、引用の source_id を解決させる。
              selectedChunkId = cid;
              selectedSourceId = null;
            }}
          />
        {/if}
      </section>
      {#if presentationStore.active}
        <aside class="viewer">
          <LiveCaptionView variant="sidebar" />
        </aside>
      {:else if viewerOpen}
        <aside class="viewer">
          <SourceViewer
            notebookId={data.notebookId}
            selectedChunkId={selectedChunkId}
            selectedSourceId={selectedSourceId}
          />
        </aside>
      {/if}
    </div>
  {/if}
</div>

<style>
  .detail {
    display: flex;
    flex-direction: column;
    height: calc(100vh - var(--header-height));
  }
  .topbar {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-5);
    border-bottom: 1px solid var(--color-border);
    background: var(--color-bg);
  }
  .topbar h2 {
    margin: 0;
    font-size: 16px;
  }
  .model-pick {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    margin-left: auto;
  }
  .model-pick-label {
    font-size: 11px;
    color: var(--color-fg-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .model-pick select {
    font-size: 12px;
    padding: 2px var(--space-2);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-bg);
    color: var(--color-fg);
    max-width: 220px;
  }
  .back {
    background: none;
    border: none;
    color: var(--color-fg-muted);
    padding: var(--space-1);
    border-radius: var(--radius-sm);
    display: inline-flex;
  }
  .back:hover {
    background: var(--color-bg-elevated);
    color: var(--color-fg);
  }
  .cols {
    flex: 1;
    display: grid;
    grid-template-columns: var(--sidebar-width) 1fr;
    min-height: 0;
  }
  .cols.viewer-open {
    grid-template-columns: var(--sidebar-width) 1fr var(--viewer-width);
  }
  .sources {
    border-right: 1px solid var(--color-border);
    background: var(--color-bg-sidebar);
    overflow-y: auto;
  }
  .chat {
    display: flex;
    flex-direction: column;
    min-height: 0;
  }
  .viewer {
    border-left: 1px solid var(--color-border);
    background: var(--color-bg-elevated);
    overflow-y: auto;
  }
  .state {
    padding: var(--space-7) 0;
    text-align: center;
    color: var(--color-fg-muted);
  }
  .err {
    color: var(--color-error);
  }
</style>

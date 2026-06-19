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
  import SourcesPanel from '$lib/components/SourcesPanel.svelte';
  import ChatPanel from '$lib/components/ChatPanel.svelte';
  import LiveCaptionView from '$lib/components/LiveCaptionView.svelte';
  import SourceViewer from '$lib/components/SourceViewer.svelte';
  import { recordingStore } from '$lib/stores/recording.svelte';

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

  // when notebook changes, reset conversation (clear messages, drop current conv ref)
  $effect(() => {
    void data.notebookId;
    // ConversationStore singleton retains across pages; clear it for new notebook
    conversationStore.cancel();
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

  {#if currentNotebookStore.loading}
    <div class="state"><Spinner /> 読み込み中…</div>
  {:else if currentNotebookStore.error}
    <div class="state err">エラー: {currentNotebookStore.error}</div>
  {:else}
    <div class="cols" class:viewer-open={viewerOpen}>
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
        {#if recordingStore.recording}
          <LiveCaptionView />
        {:else}
          <ChatPanel
            notebookId={data.notebookId}
            onCitationClick={(cid) => {
              // 引用クリック時は古いソース選択を消し、引用の source_id を解決させる。
              selectedChunkId = cid;
              selectedSourceId = null;
            }}
          />
        {/if}
      </section>
      {#if viewerOpen}
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

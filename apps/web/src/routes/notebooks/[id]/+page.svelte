<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { ArrowLeft } from '@lucide/svelte';
  import { currentNotebookStore } from '$lib/stores/currentNotebook.svelte';
  import { conversationStore } from '$lib/stores/conversation.svelte';
  import { eventsStore } from '$lib/stores/events.svelte';
  import Spinner from '$lib/components/Spinner.svelte';
  import SourcesPanel from '$lib/components/SourcesPanel.svelte';

  let { data } = $props<{ data: { notebookId: string } }>();

  let viewerOpen = $state(true);
  let selectedSourceId = $state<string | null>(null);

  onMount(async () => {
    await currentNotebookStore.load(data.notebookId);
    eventsStore.start(data.notebookId);
  });

  onDestroy(() => {
    eventsStore.stop();
    currentNotebookStore.clear();
  });
</script>

<div class="detail">
  <div class="topbar">
    <button class="back" onclick={() => goto('/')} aria-label="戻る">
      <ArrowLeft size="16" />
    </button>
    <h2>{currentNotebookStore.notebook?.name ?? '読み込み中…'}</h2>
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
          onSourceSelect={(id) => (selectedSourceId = id)}
        />
      </aside>
      <section class="chat">
        <!-- ChatPanel filled in Task 7.x -->
        <p style="padding: 16px; color: var(--color-fg-muted);">Chat (TBD)</p>
      </section>
      {#if viewerOpen}
        <aside class="viewer">
          <!-- SourceViewer filled in Task 8.x -->
          <p style="padding: 16px; color: var(--color-fg-muted);">Source Viewer (TBD)</p>
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

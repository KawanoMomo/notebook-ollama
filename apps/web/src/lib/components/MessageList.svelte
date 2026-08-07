<script lang="ts">
  import ChatMessage from './ChatMessage.svelte';
  import Spinner from './Spinner.svelte';
  import type { Citation } from '$lib/api/types';
  import { renderMarkdown } from '$lib/utils/markdown';
  import { injectCitationBadges } from '$lib/utils/citations';
  import { conversationStore } from '$lib/stores/conversation.svelte';
  import { currentNotebookStore } from '$lib/stores/currentNotebook.svelte';

  interface Props {
    activeOccurrence?: number | null;
    onCitationClick: (
      chunkId: string,
      sourceId: string,
      selection: { citation: Citation; answerOccurrence: number } | null,
    ) => void;
  }
  let { activeOccurrence = null, onCitationClick }: Props = $props();

  let scroller: HTMLDivElement | undefined = $state();
  let userScrolled = $state(false);

  const lastTruncated = $derived.by(() => {
    const m = conversationStore.messages[conversationStore.messages.length - 1];
    return !conversationStore.streaming && m?.role === 'assistant' && m?.truncated === true;
  });

  $effect(() => {
    // re-run when messages change or streaming text grows
    void conversationStore.messages;
    void conversationStore.streamingText;
    if (scroller && !userScrolled) {
      scroller.scrollTop = scroller.scrollHeight;
    }
  });

  function onScroll() {
    if (!scroller) return;
    const atBottom =
      scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 40;
    userScrolled = !atBottom;
  }
</script>

<div class="list" bind:this={scroller} onscroll={onScroll}>
  {#each conversationStore.messages as m (m.id)}
    <ChatMessage message={m} {activeOccurrence} {onCitationClick} />
  {/each}

  {#if lastTruncated}
    <div class="continue-row">
      <button
        class="continue-btn"
        type="button"
        onclick={() => conversationStore.continueLast(Array.from(currentNotebookStore.selectedSourceIds))}
      >▶ 続きを生成</button>
    </div>
  {/if}

  {#if conversationStore.streaming}
    <article class="msg streaming">
      <div class="role">アシスタント</div>
      {#if conversationStore.streamingText}
        {#if conversationStore.streamingHits.length > 0}
          <div class="hits">参照中: {conversationStore.streamingHits.length} ソース</div>
        {/if}
        <div class="content">{@html injectCitationBadges(renderMarkdown(conversationStore.streamingText), [])}</div>
        {#if conversationStore.continuingInfo}
          <div class="caret"><Spinner size={10} /> 続きを生成中… ({conversationStore.continuingInfo.round}/{conversationStore.continuingInfo.max})</div>
        {:else}
          <div class="caret"><Spinner size={10} /> 生成中…</div>
        {/if}
      {:else if conversationStore.thinkingChars > 0}
        <div class="pending">
          <Spinner size={12} />
          思考中… ({conversationStore.thinkingChars} 文字)
        </div>
      {:else}
        <div class="pending">
          <Spinner size={12} />
          {conversationStore.streamingHits.length > 0 ? '生成中…' : '参照中…'}
        </div>
      {/if}
    </article>
  {/if}

  {#if conversationStore.warning}
    <div class="warn">{conversationStore.warning}</div>
  {/if}

  {#if conversationStore.error}
    <div class="err">エラー: {conversationStore.error}</div>
  {/if}
</div>

<style>
  .list {
    flex: 1;
    overflow-y: auto;
  }
  .msg {
    padding: var(--space-4);
    border-bottom: 1px solid var(--color-border);
  }
  .role {
    font-size: 11px;
    color: var(--color-fg-muted);
    margin-bottom: var(--space-2);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .hits {
    font-size: 12px;
    color: var(--color-fg-muted);
    margin-bottom: var(--space-2);
  }
  .caret {
    margin-top: var(--space-2);
    font-size: 11px;
    color: var(--color-fg-muted);
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
  }
  .pending {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    font-size: 12px;
    color: var(--color-fg-muted);
  }
  .warn {
    padding: var(--space-2) var(--space-4);
    font-size: 12px;
    color: var(--color-warning, #b45309);
  }
  .err {
    padding: var(--space-4);
    color: var(--color-error);
  }
  .continue-row {
    padding: var(--space-2) var(--space-4);
    border-bottom: 1px solid var(--color-border);
  }
  .continue-btn {
    font: inherit;
    font-size: 12px;
    color: var(--color-accent);
    background: var(--color-bg-elevated);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-1) var(--space-3);
    cursor: pointer;
  }
  .continue-btn:hover {
    border-color: var(--color-accent);
  }
</style>

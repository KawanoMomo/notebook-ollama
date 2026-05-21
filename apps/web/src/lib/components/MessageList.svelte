<script lang="ts">
  import ChatMessage from './ChatMessage.svelte';
  import Spinner from './Spinner.svelte';
  import { renderMarkdown } from '$lib/utils/markdown';
  import { injectCitationBadges } from '$lib/utils/citations';
  import { conversationStore } from '$lib/stores/conversation.svelte';

  interface Props {
    onCitationClick: (chunkId: string) => void;
  }
  let { onCitationClick }: Props = $props();

  let scroller: HTMLDivElement | undefined = $state();
  let userScrolled = $state(false);

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
    <ChatMessage message={m} {onCitationClick} />
  {/each}

  {#if conversationStore.streaming && conversationStore.streamingText}
    <article class="msg streaming">
      <div class="role">アシスタント</div>
      {#if conversationStore.streamingHits.length > 0}
        <div class="hits">参照中: {conversationStore.streamingHits.length} ソース</div>
      {/if}
      <div class="content">{@html injectCitationBadges(renderMarkdown(conversationStore.streamingText), [])}</div>
      <div class="caret"><Spinner size={10} /> 生成中…</div>
    </article>
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
  .err {
    padding: var(--space-4);
    color: var(--color-error);
  }
</style>

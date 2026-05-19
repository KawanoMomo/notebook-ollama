<script lang="ts">
  import MessageList from './MessageList.svelte';
  import ChatInput from './ChatInput.svelte';
  import { conversationStore } from '$lib/stores/conversation.svelte';

  interface Props {
    notebookId: string;
    onCitationClick: (chunkId: string) => void;
  }
  let { notebookId, onCitationClick }: Props = $props();

  function onSend(text: string) {
    conversationStore.send(notebookId, text);
  }

  function onCitation(n: number) {
    // find chunk_id from the latest assistant message's citations
    const latest = [...conversationStore.messages]
      .reverse()
      .find((m) => m.role === 'assistant');
    if (!latest) return;
    const c = latest.citations.find((x) => x.n === n);
    if (c) onCitationClick(c.chunk_id);
  }
</script>

<MessageList onCitationClick={onCitation} />
<ChatInput
  disabled={conversationStore.streaming}
  hint={conversationStore.messages.length > 0
    ? `履歴: 直近${Math.min(3, Math.floor(conversationStore.messages.length / 2))}往復が含まれます`
    : null}
  {onSend}
/>

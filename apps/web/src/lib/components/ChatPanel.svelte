<script lang="ts">
  import MessageList from './MessageList.svelte';
  import ChatInput from './ChatInput.svelte';
  import { conversationStore } from '$lib/stores/conversation.svelte';
  import { currentNotebookStore } from '$lib/stores/currentNotebook.svelte';
  import type { Citation } from '$lib/api/types';

  interface Props {
    notebookId: string;
    activeOccurrence?: number | null;
    onCitationClick: (
      chunkId: string,
      sourceId: string,
      selection: { citation: Citation; answerOccurrence: number; messageId: string } | null,
    ) => void;
  }
  let { notebookId, activeOccurrence = null, onCitationClick }: Props = $props();

  function onSend(text: string) {
    conversationStore.send(
      notebookId,
      text,
      Array.from(currentNotebookStore.selectedSourceIds),
    );
  }
</script>

<MessageList {activeOccurrence} {onCitationClick} />
<ChatInput
  streaming={conversationStore.streaming}
  hint={conversationStore.messages.length > 0
    ? `履歴: 直近${Math.min(3, Math.floor(conversationStore.messages.length / 2))}往復が含まれます`
    : null}
  sourcesSelected={currentNotebookStore.selectedSourceIds.size}
  {onSend}
  onCancel={() => conversationStore.cancel()}
/>

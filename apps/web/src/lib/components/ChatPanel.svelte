<script lang="ts">
  import MessageList from './MessageList.svelte';
  import ChatInput from './ChatInput.svelte';
  import { conversationStore } from '$lib/stores/conversation.svelte';
  import { currentNotebookStore } from '$lib/stores/currentNotebook.svelte';

  interface Props {
    notebookId: string;
    onCitationClick: (chunkId: string) => void;
  }
  let { notebookId, onCitationClick }: Props = $props();

  function onSend(text: string) {
    conversationStore.send(
      notebookId,
      text,
      Array.from(currentNotebookStore.selectedSourceIds),
    );
  }
</script>

<MessageList {onCitationClick} />
<ChatInput
  streaming={conversationStore.streaming}
  hint={conversationStore.messages.length > 0
    ? `履歴: 直近${Math.min(3, Math.floor(conversationStore.messages.length / 2))}往復が含まれます`
    : null}
  {onSend}
  onCancel={() => conversationStore.cancel()}
/>

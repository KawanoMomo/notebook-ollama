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
</script>

<MessageList {onCitationClick} />
<ChatInput
  disabled={conversationStore.streaming}
  hint={conversationStore.messages.length > 0
    ? `履歴: 直近${Math.min(3, Math.floor(conversationStore.messages.length / 2))}往復が含まれます`
    : null}
  {onSend}
/>

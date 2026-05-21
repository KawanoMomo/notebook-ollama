import type {
  Citation,
  Conversation,
  Message,
  RetrievalHit,
} from "$lib/api/types";
import { chatApi, type ChatEvent } from "$lib/api/chat";
import { notify, requestPermissionOnce } from "$lib/utils/notifications";

export interface ConversationStore {
  readonly conversation: Conversation | null;
  readonly messages: Message[];
  readonly streaming: boolean;
  readonly streamingText: string;
  readonly streamingHits: RetrievalHit[];
  readonly error: string | null;
  load(notebookId: string, conversationId: string): Promise<void>;
  ensureConversation(notebookId: string): Promise<Conversation>;
  send(notebookId: string, content: string): Promise<void>;
  cancel(): void;
}

export function createConversationStore(api = chatApi): ConversationStore {
  let conversation = $state<Conversation | null>(null);
  let messages = $state<Message[]>([]);
  let streaming = $state(false);
  let streamingText = $state("");
  let streamingHits = $state<RetrievalHit[]>([]);
  let error = $state<string | null>(null);
  let abortController: AbortController | null = null;

  return {
    get conversation() {
      return conversation;
    },
    get messages() {
      return messages;
    },
    get streaming() {
      return streaming;
    },
    get streamingText() {
      return streamingText;
    },
    get streamingHits() {
      return streamingHits;
    },
    get error() {
      return error;
    },
    async load(notebookId, conversationId) {
      const items = await api.listMessages(notebookId, conversationId);
      messages = items;
      // conversation metadata isn't fetched here; caller may set separately
    },
    async ensureConversation(notebookId) {
      if (conversation) return conversation;
      conversation = await api.createConversation(notebookId);
      messages = [];
      return conversation;
    },
    async send(notebookId, content) {
      void requestPermissionOnce();
      const conv = await this.ensureConversation(notebookId);
      // optimistically add user message
      const userMsg: Message = {
        id: `tmp-${Date.now()}`,
        conversation_id: conv.id,
        role: "user",
        content,
        citations: [],
        model: null,
        created_at: new Date().toISOString(),
      };
      messages = [...messages, userMsg];
      streaming = true;
      streamingText = "";
      streamingHits = [];
      error = null;
      abortController = new AbortController();
      const questionPreview = content.slice(0, 40);
      try {
        let citations: Citation[] = [];
        let modelUsed: string | null = null;
        for await (const ev of api.sendMessage(
          notebookId,
          conv.id,
          content,
          abortController.signal,
        ) as AsyncGenerator<ChatEvent>) {
          if (ev.kind === "retrieval") {
            streamingHits = ev.hits;
          } else if (ev.kind === "token") {
            streamingText += ev.text;
          } else if (ev.kind === "done") {
            citations = ev.citations;
            modelUsed = ev.model_used;
            streamingText = ev.answer;
          } else if (ev.kind === "error") {
            error = ev.message;
          }
        }
        const assistantMsg: Message = {
          id: `tmp-asst-${Date.now()}`,
          conversation_id: conv.id,
          role: "assistant",
          content: streamingText,
          citations,
          model: modelUsed,
          created_at: new Date().toISOString(),
        };
        messages = [...messages, assistantMsg];
        if (error) {
          notify({ title: "回答エラー", body: error.slice(0, 80), tag: "chat-error" });
        } else {
          notify({ title: "回答完了", body: questionPreview, tag: "chat-done" });
        }
      } catch (e) {
        error = e instanceof Error ? e.message : String(e);
        notify({ title: "回答エラー", body: error.slice(0, 80), tag: "chat-error" });
      } finally {
        streaming = false;
        streamingText = "";
        streamingHits = [];
        abortController = null;
      }
    },
    cancel() {
      abortController?.abort();
    },
  };
}

export const conversationStore = createConversationStore();

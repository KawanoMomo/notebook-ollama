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
  readonly warning: string | null;
  readonly lastBeatAt: number | null;
  load(notebookId: string, conversationId: string): Promise<void>;
  ensureConversation(notebookId: string): Promise<Conversation>;
  send(notebookId: string, content: string, sourceIds?: string[]): Promise<void>;
  cancel(): void;
}

export function createConversationStore(api = chatApi): ConversationStore {
  let conversation = $state<Conversation | null>(null);
  let messages = $state<Message[]>([]);
  let streaming = $state(false);
  let streamingText = $state("");
  let streamingHits = $state<RetrievalHit[]>([]);
  let error = $state<string | null>(null);
  let warning = $state<string | null>(null);
  let lastBeatAt = $state<number | null>(null);
  let beatTimer: ReturnType<typeof setInterval> | null = null;
  const NO_BEAT_WARNING_MS = 60_000;

  function beat() {
    lastBeatAt = Date.now();
    if (warning) warning = null;
  }

  function startBeatWatch() {
    stopBeatWatch();
    beat();
    beatTimer = setInterval(() => {
      if (lastBeatAt !== null && Date.now() - lastBeatAt >= NO_BEAT_WARNING_MS) {
        warning = 'Ollamaが応答していない可能性があります';
      }
    }, 5_000);
  }

  function stopBeatWatch() {
    if (beatTimer !== null) {
      clearInterval(beatTimer);
      beatTimer = null;
    }
  }

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
    get warning() {
      return warning;
    },
    get lastBeatAt() {
      return lastBeatAt;
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
    async send(notebookId, content, sourceIds) {
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
      warning = null;
      abortController = new AbortController();
      startBeatWatch();
      const questionPreview = content.slice(0, 40);
      try {
        let citations: Citation[] = [];
        let modelUsed: string | null = null;
        for await (const ev of api.sendMessage(
          notebookId,
          conv.id,
          content,
          sourceIds,
          abortController.signal,
        ) as AsyncGenerator<ChatEvent>) {
          beat();
          if (ev.kind === "ping") {
            // beat() 済み。接続生存のみ確認
          } else if (ev.kind === "retrieval") {
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
        stopBeatWatch();
        lastBeatAt = null;
        warning = null;
      }
    },
    cancel() {
      abortController?.abort();
      stopBeatWatch();
    },
  };
}

export const conversationStore = createConversationStore();

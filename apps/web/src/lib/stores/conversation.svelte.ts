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
  /** 思考モデルの thinking フェーズ累計文字数(0=非思考)。 */
  readonly thinkingChars: number;
  readonly error: string | null;
  readonly warning: string | null;
  readonly lastBeatAt: number | null;
  load(notebookId: string, conversationId: string): Promise<void>;
  ensureConversation(notebookId: string): Promise<Conversation>;
  send(notebookId: string, content: string, sourceIds?: string[]): Promise<void>;
  cancel(): void;
  renameSpeakerInSource(sourceId: string, fromLabel: string, toLabel: string): void;
}

export function createConversationStore(api = chatApi): ConversationStore {
  let conversation = $state<Conversation | null>(null);
  let messages = $state<Message[]>([]);
  let streaming = $state(false);
  let streamingText = $state("");
  let streamingHits = $state<RetrievalHit[]>([]);
  let thinkingChars = $state(0);
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
    get thinkingChars() {
      return thinkingChars;
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
      thinkingChars = 0;
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
          } else if (ev.kind === "thinking") {
            thinkingChars += ev.text.length;
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
        // ユーザーが「停止」した場合(signal.aborted)は中断であってエラーではないので
        // エラーバナー/通知を出さない。それ以外の例外のみ error として表面化する。
        if (!abortController?.signal.aborted) {
          error = e instanceof Error ? e.message : String(e);
          notify({ title: "回答エラー", body: error.slice(0, 80), tag: "chat-error" });
        }
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
    renameSpeakerInSource(sourceId, fromLabel, toLabel) {
      // 話者リネーム成功時、チャット内に既に描画済みの引用カードの表示も更新する
      // (spec §3.2「右パネル・チャット内の引用とも新名称に更新」)。録音引用の
      // location は "<話者> <HH:MM:SS>"(locations.format_location)なので、先頭の
      // 話者ラベルだけを置換する。完全一致(話者のみ)/ "ラベル " 前方一致のみ対象に
      // して、部分語の誤マッチを避ける。
      if (!fromLabel || fromLabel === toLabel) return;
      const prefix = `${fromLabel} `;
      let changed = false;
      const next = messages.map((m) => {
        if (!m.citations?.length) return m;
        let touched = false;
        const cites = m.citations.map((c) => {
          if (c.source_id !== sourceId) return c;
          let loc = c.location;
          if (loc === fromLabel) {
            loc = toLabel;
          } else if (loc.startsWith(prefix)) {
            loc = toLabel + loc.slice(fromLabel.length);
          } else {
            return c;
          }
          touched = true;
          return { ...c, location: loc };
        });
        if (!touched) return m;
        changed = true;
        return { ...m, citations: cites };
      });
      if (changed) messages = next;
    },
  };
}

export const conversationStore = createConversationStore();

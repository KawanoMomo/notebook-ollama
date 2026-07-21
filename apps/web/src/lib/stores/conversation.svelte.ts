import type {
  Citation,
  Conversation,
  Message,
  RetrievalHit,
} from "$lib/api/types";
import { chatApi, type ChatEvent } from "$lib/api/chat";
import { notify, requestPermissionOnce } from "$lib/utils/notifications";
import { stripTruncationNote } from "$lib/utils/truncation";

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
  /** continuing イベント受信中の進捗(自動継続ラウンド)。token 到着 or done で null に戻る。 */
  readonly continuingInfo: { round: number; max: number } | null;
  load(notebookId: string, conversationId: string): Promise<void>;
  /** ノートを開いた時に、そのノートの最新会話を復元する(履歴のノートスコープ化)。 */
  loadLatest(notebookId: string): Promise<void>;
  ensureConversation(notebookId: string): Promise<Conversation>;
  send(notebookId: string, content: string, sourceIds?: string[]): Promise<void>;
  /** 打ち切られた最後の応答(truncated=true)の続きを生成し、1通のメッセージに載せ替える(issue #22)。 */
  continueLast(sourceIds?: string[]): Promise<void>;
  cancel(): void;
  /** 会話・メッセージ・ストリーミング状態を全クリアする(ノート切替時に呼ぶ)。 */
  reset(): void;
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
  let continuingInfo = $state<{ round: number; max: number } | null>(null);
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
    get continuingInfo() {
      return continuingInfo;
    },
    async load(notebookId, conversationId) {
      const items = await api.listMessages(notebookId, conversationId);
      messages = items;
      // conversation metadata isn't fetched here; caller may set separately
    },
    async loadLatest(notebookId) {
      // そのノートの最新会話 1 件を復元する。無ければ何もしない(空のまま)。
      // 呼び出し前に reset() 済みであること想定(+page.svelte の $effect が担保)。
      const convs = await api.listConversations(notebookId);
      if (convs.length === 0) return;
      const latest = convs[0]; // list_conversations は updated_at DESC で返る(BE契約)
      const items = await api.listMessages(notebookId, latest.id);
      conversation = latest;
      messages = items;
    },
    async ensureConversation(notebookId) {
      // 別ノートの会話を保持したまま呼ばれた場合は新規発行に切替
      // (BE の 404 ガードに頼らず FE 側で防ぐ二重ガード)。
      if (conversation && conversation.notebook_id === notebookId) {
        return conversation;
      }
      conversation = await api.createConversation(notebookId);
      messages = [];
      return conversation;
    },
    reset() {
      // ノート切替時: 送信中なら abort し、状態を全クリア。
      abortController?.abort();
      stopBeatWatch();
      abortController = null;
      conversation = null;
      messages = [];
      streaming = false;
      streamingText = "";
      streamingHits = [];
      thinkingChars = 0;
      error = null;
      warning = null;
      lastBeatAt = null;
      continuingInfo = null;
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
      continuingInfo = null;
      abortController = new AbortController();
      startBeatWatch();
      const questionPreview = content.slice(0, 40);
      try {
        let citations: Citation[] = [];
        let modelUsed: string | null = null;
        let lastTruncated = false;
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
          } else if (ev.kind === "continuing") {
            continuingInfo = { round: ev.round, max: ev.max };
          } else if (ev.kind === "token") {
            if (continuingInfo) continuingInfo = null; // 続きが流れ始めたら表示解除
            streamingText += ev.text;
          } else if (ev.kind === "done") {
            citations = ev.citations;
            modelUsed = ev.model_used;
            streamingText = ev.answer;
            lastTruncated = ev.truncated;
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
          truncated: lastTruncated,
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
        continuingInfo = null;
        abortController = null;
        stopBeatWatch();
        lastBeatAt = null;
        warning = null;
      }
    },
    async continueLast(sourceIds) {
      if (!conversation) return;
      const last = messages[messages.length - 1];
      if (!last || last.role !== "assistant" || !last.truncated || streaming) return;
      const nbId = conversation.notebook_id;
      // 最後のメッセージを streaming 表示へ載せ替える(1つの吹き出しに見せる)。
      messages = messages.slice(0, -1);
      streaming = true;
      // 旧注記(打ち切り警告)を残したまま継続表示すると、継続ストリーミング中
      // ずっと本文中央に警告が挟まって見えるため、シード時点で除去する。
      streamingText = stripTruncationNote(last.content);
      thinkingChars = 0;
      streamingHits = [];
      continuingInfo = null;
      error = null;
      warning = null;
      abortController = new AbortController();
      startBeatWatch();
      let citations = last.citations;
      let modelUsed = last.model;
      let lastTruncated = true;
      let finalText = last.content;
      try {
        for await (const ev of api.continueMessage(
          nbId,
          conversation.id,
          sourceIds,
          abortController.signal,
        ) as AsyncGenerator<ChatEvent>) {
          beat();
          if (ev.kind === "ping") {
            // 接続生存のみ
          } else if (ev.kind === "retrieval") {
            streamingHits = ev.hits;
          } else if (ev.kind === "thinking") {
            thinkingChars += ev.text.length;
          } else if (ev.kind === "continuing") {
            continuingInfo = { round: ev.round, max: ev.max };
          } else if (ev.kind === "token") {
            if (continuingInfo) continuingInfo = null;
            streamingText += ev.text;
          } else if (ev.kind === "done") {
            citations = ev.citations;
            modelUsed = ev.model_used;
            streamingText = ev.answer;
            finalText = ev.answer;
            lastTruncated = ev.truncated;
          } else if (ev.kind === "error") {
            error = ev.message;
          }
        }
      } catch (e) {
        if (!abortController?.signal.aborted) {
          error = e instanceof Error ? e.message : String(e);
        }
      } finally {
        messages = [
          ...messages,
          {
            ...last,
            content: error ? last.content : finalText || streamingText || last.content,
            citations,
            model: modelUsed,
            truncated: error ? last.truncated : lastTruncated,
          },
        ];
        // send() と同様の通知。中断(abort)時は send() 同様エラー扱いしない
        // ので通知もしない。質問文は continueLast からは直接見えないため
        // body は固定短文で済ませる。
        if (!abortController?.signal.aborted) {
          if (error) {
            notify({ title: "回答エラー", body: error.slice(0, 80), tag: "chat-error" });
          } else {
            notify({
              title: "回答完了",
              body: "続きの生成が完了しました",
              tag: "chat-done",
            });
          }
        }
        streaming = false;
        streamingText = "";
        streamingHits = [];
        continuingInfo = null;
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

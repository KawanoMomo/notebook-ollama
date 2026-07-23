import { request } from './client';
import type { Citation, Conversation, Message, RetrievalHit } from './types';

export type ChatEvent =
  | { kind: 'retrieval'; hits: RetrievalHit[] }
  | { kind: 'token'; text: string }
  | { kind: 'thinking'; text: string }
  | { kind: 'continuing'; round: number; max: number }
  | {
      kind: 'done';
      answer: string;
      citations: Citation[];
      model_used: string;
      dropped_history: number;
      truncated: boolean;
      continued_rounds: number;
    }
  | { kind: 'error'; code: string; message: string }
  | { kind: 'ping' };

/**
 * Open an SSE stream against `url`, POSTing `body`. Yields parsed ChatEvent
 * for each `event:`/`data:` pair. Shared by sendMessage and continueMessage.
 */
async function* streamSse(
  url: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<ChatEvent, void, unknown> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok || !response.body) {
    const text = await response.text();
    throw new Error(`chat stream failed: ${response.status} ${text}`);
  }
  const reader = response.body
    .pipeThrough(new TextDecoderStream())
    .getReader();
  let buffer = '';
  let currentEvent: string | null = null;
  while (true) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += value;
    let idx: number;
    while ((idx = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, idx).replace(/\r$/, '');
      buffer = buffer.slice(idx + 1);
      if (line.startsWith('event:')) {
        currentEvent = line.slice(6).trim();
      } else if (line.startsWith('data:')) {
        const data = line.slice(5).trim();
        if (data && currentEvent) {
          try {
            const parsed = JSON.parse(data);
            yield { kind: currentEvent, ...parsed } as ChatEvent;
          } catch {
            // ignore malformed
          }
        }
      } else if (line === '') {
        currentEvent = null;
      }
    }
  }
}

export const chatApi = {
  createConversation: (notebookId: string) =>
    request<Conversation>(`/api/notebooks/${notebookId}/conversations`, {
      method: 'POST',
    }),

  listConversations: (notebookId: string) =>
    request<Conversation[]>(`/api/notebooks/${notebookId}/conversations`),

  listMessages: (notebookId: string, conversationId: string) =>
    request<Message[]>(
      `/api/notebooks/${notebookId}/conversations/${conversationId}/messages`,
    ),

  /**
   * Open an SSE stream for a chat reply. Returns an async iterator over events.
   */
  sendMessage: (
    notebookId: string,
    conversationId: string,
    content: string,
    sourceIds?: string[],
    signal?: AbortSignal,
  ) =>
    streamSse(
      `/api/notebooks/${notebookId}/conversations/${conversationId}/messages`,
      { content, source_ids: sourceIds },
      signal,
    ),

  /** 打ち切られた最後の応答の続きを生成する(issue #22)。 */
  continueMessage: (
    notebookId: string,
    conversationId: string,
    sourceIds?: string[],
    signal?: AbortSignal,
  ) =>
    streamSse(
      `/api/notebooks/${notebookId}/conversations/${conversationId}/continue`,
      { source_ids: sourceIds },
      signal,
    ),
};

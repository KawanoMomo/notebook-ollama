import { request } from './client';
import type { Citation, Conversation, Message, RetrievalHit } from './types';

export type ChatEvent =
  | { kind: 'retrieval'; hits: RetrievalHit[] }
  | { kind: 'token'; text: string }
  | {
      kind: 'done';
      answer: string;
      citations: Citation[];
      model_used: string;
      dropped_history: number;
    }
  | { kind: 'error'; code: string; message: string }
  | { kind: 'ping' };

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
  sendMessage: async function* (
    notebookId: string,
    conversationId: string,
    content: string,
    sourceIds?: string[],
    signal?: AbortSignal,
  ): AsyncGenerator<ChatEvent, void, unknown> {
    const url = `/api/notebooks/${notebookId}/conversations/${conversationId}/messages`;
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ content, source_ids: sourceIds }),
      signal,
    });
    if (!response.ok || !response.body) {
      const body = await response.text();
      throw new Error(`chat stream failed: ${response.status} ${body}`);
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
  },
};

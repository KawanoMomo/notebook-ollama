/**
 * feedback-hub API client.
 *
 * Matches backend `apps/api/routers/feedback_hub.py` 1:1.
 *
 * Endpoints:
 * - `GET  /api/feedback-hub/notices`       — listNotices()
 * - `GET  /api/feedback-hub/unread-count`  — unreadCount()
 * - `POST /api/feedback-hub/feedback`      — submitFeedback(input)
 *
 * Spec: docs/specs/2026-06-28-crash-report-feedback-hub-design.md
 *
 * Note on `listNotices`: the backend returns `{ notices: Notice[] }`
 * (Pydantic `NoticesOut` envelope) so we unwrap to a plain array — the
 * envelope leaks no useful metadata and consumers want `Notice[]` directly.
 */
import { request } from './client';
import type { FeedbackInput, Notice, UnreadCount } from './types';

interface NoticesEnvelope {
  notices: Notice[];
}

interface FeedbackResponse {
  prefill_url: string;
}

export const feedbackHubApi = {
  listNotices: async (): Promise<Notice[]> => {
    const { notices } = await request<NoticesEnvelope>('/api/feedback-hub/notices');
    return notices;
  },

  unreadCount: () => request<UnreadCount>('/api/feedback-hub/unread-count'),

  submitFeedback: (input: FeedbackInput) =>
    request<FeedbackResponse>('/api/feedback-hub/feedback', {
      method: 'POST',
      body: JSON.stringify(input),
    }),
};

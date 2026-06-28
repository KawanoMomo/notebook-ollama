/**
 * feedback-hub API client tests (Sprint 5 Task 5.2).
 *
 * Boundary coverage checklist (Sprint 1-3 lessons):
 * - Empty notices list, single-element, multi-element.
 * - Unicode CJK + emoji preserved through JSON serialization.
 * - Parametrize over the full FeedbackKind + Sentiment enums.
 * - Optional fields (sentiment, screenshot_b64) — null / undefined / present.
 * - Oversize body forwarded verbatim (server enforces 50_000 / 3_000_000 limits).
 * - 4xx + 5xx error paths surface as ApiError.
 * - listNotices unwraps backend `{ notices: [...] }` envelope.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '$lib/api/client';
import { feedbackHubApi } from '$lib/api/feedbackHub';
import type {
  FeedbackInput,
  FeedbackKind,
  Notice,
  Sentiment,
} from '$lib/api/types';

const originalFetch = global.fetch;
const fetchMock = () => global.fetch as ReturnType<typeof vi.fn>;

/** Full registry of FeedbackKind (must match `FeedbackKind` exactly). */
const ALL_KINDS: FeedbackKind[] = ['feature', 'complaint', 'impression'];

/** Full registry of Sentiment (must match `Sentiment` exactly). */
const ALL_SENTIMENTS: Sentiment[] = ['up', 'neutral', 'down'];

const sampleNotice: Notice = {
  id: 'n-2026-06-28-01',
  date: '2026-06-28',
  title: 'リリースノート v0.5',
  body: '本リリースの概要。',
  subsections: [
    { heading: '新機能', items: ['クラッシュ自動収集', 'フィードバックハブ'] },
  ],
};

const jsonResponse = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const errorResponse = (status: number, code: string, message: string): Response =>
  new Response(
    JSON.stringify({ error: { code, message, detail: null, remediation: null } }),
    { status, headers: { 'Content-Type': 'application/json' } },
  );

describe('feedbackHubApi.listNotices', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('GETs /api/feedback-hub/notices and unwraps the `notices` envelope', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse({ notices: [sampleNotice] }));
    const out = await feedbackHubApi.listNotices();
    const [url, init] = fetchMock().mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/feedback-hub/notices');
    expect(init?.method ?? 'GET').toBe('GET');
    expect(out).toEqual([sampleNotice]);
  });

  it('returns [] when backend returns { notices: [] }', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse({ notices: [] }));
    const out = await feedbackHubApi.listNotices();
    expect(out).toEqual([]);
  });

  it('preserves multiple notices in order', async () => {
    const a = { ...sampleNotice, id: 'a', date: '2026-06-28' };
    const b = { ...sampleNotice, id: 'b', date: '2026-06-27' };
    fetchMock().mockResolvedValueOnce(jsonResponse({ notices: [a, b] }));
    const out = await feedbackHubApi.listNotices();
    expect(out.map((n) => n.id)).toEqual(['a', 'b']);
  });

  it('throws ApiError on 500', async () => {
    fetchMock().mockResolvedValueOnce(errorResponse(500, 'internal', 'boom'));
    await expect(feedbackHubApi.listNotices()).rejects.toBeInstanceOf(ApiError);
  });
});

describe('feedbackHubApi.unreadCount', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('GETs /api/feedback-hub/unread-count and returns the wrapped object', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse({ count: 3 }));
    const out = await feedbackHubApi.unreadCount();
    const [url, init] = fetchMock().mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/feedback-hub/unread-count');
    expect(init?.method ?? 'GET').toBe('GET');
    expect(out).toEqual({ count: 3 });
  });

  it('handles zero count', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse({ count: 0 }));
    const out = await feedbackHubApi.unreadCount();
    expect(out.count).toBe(0);
  });

  it('throws ApiError on 500', async () => {
    fetchMock().mockResolvedValueOnce(errorResponse(500, 'internal', 'boom'));
    await expect(feedbackHubApi.unreadCount()).rejects.toBeInstanceOf(ApiError);
  });
});

describe('feedbackHubApi.submitFeedback', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('POSTs /api/feedback-hub/feedback with JSON body and returns prefill_url', async () => {
    fetchMock().mockResolvedValueOnce(
      jsonResponse({ prefill_url: 'https://github.com/x/y/issues/new?title=...' }),
    );
    const payload: FeedbackInput = {
      kind: 'feature',
      body: 'tab を保存してほしい',
      sentiment: 'up',
    };
    const out = await feedbackHubApi.submitFeedback(payload);
    const [url, init] = fetchMock().mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/feedback-hub/feedback');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual(payload);
    expect(out).toEqual({ prefill_url: 'https://github.com/x/y/issues/new?title=...' });
  });

  it.each(ALL_KINDS)('serializes kind=%s (parametrized over FeedbackKind enum)', async (kind) => {
    fetchMock().mockResolvedValueOnce(jsonResponse({ prefill_url: 'https://x' }));
    await feedbackHubApi.submitFeedback({ kind, body: 'b' });
    const [, init] = fetchMock().mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string).kind).toBe(kind);
  });

  it.each(ALL_SENTIMENTS)(
    'serializes sentiment=%s (parametrized over Sentiment enum)',
    async (sentiment) => {
      fetchMock().mockResolvedValueOnce(jsonResponse({ prefill_url: 'https://x' }));
      await feedbackHubApi.submitFeedback({ kind: 'feature', body: 'b', sentiment });
      const [, init] = fetchMock().mock.calls[0] as [string, RequestInit];
      expect(JSON.parse(init.body as string).sentiment).toBe(sentiment);
    },
  );

  it('omits absent optional fields rather than sending undefined', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse({ prefill_url: 'https://x' }));
    await feedbackHubApi.submitFeedback({ kind: 'impression', body: 'b' });
    const [, init] = fetchMock().mock.calls[0] as [string, RequestInit];
    const parsed = JSON.parse(init.body as string);
    expect(parsed).toEqual({ kind: 'impression', body: 'b' });
    expect('sentiment' in parsed).toBe(false);
    expect('screenshot_b64' in parsed).toBe(false);
  });

  it('preserves explicit null sentiment / screenshot_b64', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse({ prefill_url: 'https://x' }));
    await feedbackHubApi.submitFeedback({
      kind: 'complaint',
      body: 'b',
      sentiment: null,
      screenshot_b64: null,
    });
    const [, init] = fetchMock().mock.calls[0] as [string, RequestInit];
    const parsed = JSON.parse(init.body as string);
    expect(parsed.sentiment).toBeNull();
    expect(parsed.screenshot_b64).toBeNull();
  });

  it('preserves CJK + emoji in body verbatim', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse({ prefill_url: 'https://x' }));
    const cjkEmoji = 'これは要望です 🚀 全角スペースも　保持';
    await feedbackHubApi.submitFeedback({ kind: 'feature', body: cjkEmoji });
    const [, init] = fetchMock().mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string).body).toBe(cjkEmoji);
  });

  it('forwards a base64 screenshot string verbatim', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse({ prefill_url: 'https://x' }));
    // 100KB of base64 — well under the 3MB server cap.
    const b64 = 'A'.repeat(100_000);
    await feedbackHubApi.submitFeedback({
      kind: 'complaint',
      body: 'b',
      screenshot_b64: b64,
    });
    const [, init] = fetchMock().mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string).screenshot_b64.length).toBe(100_000);
  });

  it('throws ApiError on 422 blank-body validation', async () => {
    fetchMock().mockResolvedValueOnce(
      errorResponse(422, 'validation.body', 'body must not be blank'),
    );
    await expect(
      feedbackHubApi.submitFeedback({ kind: 'feature', body: '   ' }),
    ).rejects.toMatchObject({ status: 422 });
  });

  it('throws ApiError on 500', async () => {
    fetchMock().mockResolvedValueOnce(errorResponse(500, 'internal', 'boom'));
    await expect(
      feedbackHubApi.submitFeedback({ kind: 'feature', body: 'b' }),
    ).rejects.toBeInstanceOf(ApiError);
  });
});

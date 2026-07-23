import { afterEach, describe, expect, it, vi } from 'vitest';
import { chatApi } from '$lib/api/chat';

function sseResponse(text: string): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      c.enqueue(new TextEncoder().encode(text));
      c.close();
    },
  });
  return new Response(stream, { status: 200 });
}

afterEach(() => vi.unstubAllGlobals());

describe('chatApi.continueMessage', () => {
  it('POSTs to /continue and yields continuing/done events', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse(
        'event: continuing\ndata: {"round":1,"max":2}\n\n' +
          'event: token\ndata: {"text":"続き"}\n\n' +
          'event: done\ndata: {"answer":"全文","citations":[],"model_used":"m","dropped_history":0,"truncated":false,"continued_rounds":1}\n\n',
      ),
    );
    vi.stubGlobal('fetch', fetchMock);
    const events = [];
    for await (const ev of chatApi.continueMessage('nb1', 'c1', ['s1'])) {
      events.push(ev);
    }
    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/notebooks/nb1/conversations/c1/continue',
    );
    expect(events[0]).toEqual({ kind: 'continuing', round: 1, max: 2 });
    const done = events.find((e) => e.kind === 'done');
    expect(done).toMatchObject({ truncated: false, continued_rounds: 1 });
  });
});

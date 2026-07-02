import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, request } from '$lib/api/client';

const originalFetch = global.fetch;

describe('api client', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('returns parsed JSON on 2xx', async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      new Response(JSON.stringify({ id: 'abc', name: 'N' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    const out = await request('/api/notebooks/abc');
    expect(out).toEqual({ id: 'abc', name: 'N' });
  });

  it('throws ApiError with code on 4xx', async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error: {
            code: 'storage.not_found',
            message: 'notebook xyz not found',
            detail: null,
            remediation: null,
          },
        }),
        { status: 404, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    await expect(request('/api/notebooks/xyz')).rejects.toMatchObject({
      code: 'storage.not_found',
      status: 404,
      message: 'notebook xyz not found',
    });
  });

  it('throws ApiError with detail as message on FastAPI raw HTTPException ({detail} shape)', async () => {
    // apps/api/routers/{crash,audio,recordings}.py raise plain FastAPI
    // HTTPException (not AppError), which serializes as {"detail": "..."}
    // instead of the AppError envelope {"error": {code, message, ...}}.
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: 'crash abc123 not found' }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    await expect(request('/api/crash/abc123/prefill-url')).rejects.toMatchObject({
      code: 'http.error',
      status: 404,
      message: 'crash abc123 not found',
    });
  });

  it('throws ApiError on network failure', async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('network'));
    await expect(request('/api/notebooks')).rejects.toBeInstanceOf(ApiError);
  });

  it('returns undefined for 204', async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      new Response(null, { status: 204 }),
    );
    const out = await request('/api/notebooks/abc', { method: 'DELETE' });
    expect(out).toBeUndefined();
  });
});

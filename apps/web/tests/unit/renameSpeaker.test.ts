import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { sourceDetailApi } from '$lib/api/source_outline';

const originalFetch = global.fetch;

describe('sourceDetailApi.renameSpeaker', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('PATCHes the speaker endpoint with from/to labels and returns updated count', async () => {
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ updated: 12 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const out = await sourceDetailApi.renameSpeaker('nb1', 'src1', '相手1', '田中さん');

    expect(out).toEqual({ updated: 12 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/notebooks/nb1/sources/src1/speaker');
    expect(init.method).toBe('PATCH');
    expect(JSON.parse(init.body as string)).toEqual({
      from_label: '相手1',
      to_label: '田中さん',
    });
  });

  it('propagates ApiError on failure', async () => {
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error: { code: 'validation.invalid', message: 'to_label is empty', detail: null, remediation: null },
        }),
        { status: 400, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    await expect(
      sourceDetailApi.renameSpeaker('nb1', 'src1', '相手1', ''),
    ).rejects.toMatchObject({ code: 'validation.invalid', status: 400 });
  });
});

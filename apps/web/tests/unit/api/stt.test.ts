import { afterEach, describe, expect, it, vi } from 'vitest';
import { sttApi } from '$lib/api/stt';

afterEach(() => vi.restoreAllMocks());

describe('sttApi.transcribe', () => {
  it('multipart POST して結果を返す', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ text: 'こんにちは', duration_ms: 500 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const blob = new Blob([new Uint8Array(4)], { type: 'audio/wav' });
    const result = await sttApi.transcribe(blob);

    expect(result).toEqual({ text: 'こんにちは', duration_ms: 500 });
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe('/api/stt/transcribe');
    expect(init?.method).toBe('POST');
    expect(init?.body).toBeInstanceOf(FormData);
    const form = init?.body as FormData;
    expect(form.get('file')).toBeInstanceOf(Blob);
  });

  it('503 は ApiError として伝播する', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'recording extras not installed' }), {
        status: 503,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    await expect(sttApi.transcribe(new Blob([]))).rejects.toMatchObject({
      status: 503,
    });
  });
});

import { afterEach, describe, expect, it, vi } from 'vitest';
import { translateStream } from '../../src/lib/api/translate';

afterEach(() => vi.unstubAllGlobals());

function sseResponse(lines: string[]) {
  const body = lines.map((l) => `data: ${l}\n\n`).join('');
  return {
    ok: true,
    body: {
      getReader() {
        let sent = false;
        return {
          read: async () => {
            if (sent) return { done: true, value: undefined };
            sent = true;
            return { done: false, value: new TextEncoder().encode(body) };
          },
        };
      },
    },
  };
}

describe('translateStream', () => {
  it('トークンを順に渡す', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        sseResponse([
          JSON.stringify({ text: 'これは' }),
          JSON.stringify({ text: '訳文' }),
          JSON.stringify({ done: true }),
        ]),
      ),
    );
    const got: string[] = [];
    await translateStream('Hello', (t) => got.push(t));
    expect(got.join('')).toBe('これは訳文');
  });

  it('409(生成中)では例外を投げずに終わる', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 409 })));
    const got: string[] = [];
    await expect(translateStream('Hello', (t) => got.push(t))).resolves.toBeUndefined();
    expect(got).toEqual([]);
  });

  it('error イベントはトークンとして渡さない', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => sseResponse([JSON.stringify({ error: 'boom' }), JSON.stringify({ done: true })])),
    );
    const got: string[] = [];
    await translateStream('Hello', (t) => got.push(t));
    expect(got).toEqual([]);
  });

  it('ネットワーク例外でも投げない', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
    await expect(translateStream('Hello', () => {})).resolves.toBeUndefined();
  });
});

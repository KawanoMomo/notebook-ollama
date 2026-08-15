import { afterEach, describe, expect, it, vi } from 'vitest';
import { resolveSpans } from '../../src/lib/api/spans';

afterEach(() => vi.unstubAllGlobals());

describe('resolveSpans', () => {
  it('spans を返す', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        json: async () => ({
          method: 'embedding',
          spans: [
            {
              answer_occurrence: 0,
              ordinal: null,
              start: 1,
              end: 5,
              quote: 'abcd',
              method: 'embedding',
            },
          ],
        }),
      })),
    );
    const got = await resolveSpans('m1', 3, 0);
    expect(got).toHaveLength(1);
    expect(got[0].method).toBe('embedding');
  });

  it('409(生成中)では空配列を返して例外を投げない', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 409 })));
    await expect(resolveSpans('m1', 3, 0)).resolves.toEqual([]);
  });

  it('その他のエラーでも空配列を返す(閲覧を妨げない)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500 })));
    await expect(resolveSpans('m1', 3, 0)).resolves.toEqual([]);
  });
});

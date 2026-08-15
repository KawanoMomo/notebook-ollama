import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchPageRects, pageImageUrl } from '../../src/lib/api/pages';
import { toPercentBox } from '../../src/lib/utils/pageGeometry';
import { canShowOriginal } from '../../src/lib/utils/originalTab';

afterEach(() => vi.unstubAllGlobals());

describe('pages api', () => {
  it('画像URLを組み立てる', () => {
    expect(pageImageUrl('nb', 'src', 3)).toBe('/api/notebooks/nb/sources/src/pages/3?dpi=150');
    expect(pageImageUrl('nb', 'src', 3, 300)).toContain('dpi=300');
  });

  it('矩形を取得する', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        json: async () => ({
          rects: [{ x: 1, y: 2, w: 3, h: 4 }],
          source: 'asset',
          page_width: 1240,
          page_height: 1754,
        }),
      })),
    );
    const got = await fetchPageRects('nb', 'src', 1, 'c1', 'quote');
    expect(got.source).toBe('asset');
    expect(got.rects).toHaveLength(1);
  });

  it('失敗しても例外を投げず空を返す(閲覧を妨げない)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500 })));
    await expect(fetchPageRects('nb', 'src', 1, 'c1', 'q')).resolves.toEqual({
      rects: [],
      source: 'none',
      page_width: 0,
      page_height: 0,
    });
  });
});

describe('toPercentBox', () => {
  it('自然サイズに対する百分率へ変換する', () => {
    expect(toPercentBox({ x: 50, y: 100, w: 200, h: 40 }, 1000, 2000)).toEqual({
      left: '5%',
      top: '5%',
      width: '20%',
      height: '2%',
    });
  });

  it('自然サイズが未確定(0)なら 0% を返して壊れない', () => {
    expect(toPercentBox({ x: 10, y: 10, w: 10, h: 10 }, 0, 0)).toEqual({
      left: '0%',
      top: '0%',
      width: '0%',
      height: '0%',
    });
  });

  it('はみ出す矩形は 100% に丸める', () => {
    const got = toPercentBox({ x: 900, y: 0, w: 500, h: 10 }, 1000, 1000);
    expect(got.left).toBe('90%');
    expect(got.width).toBe('10%');
  });
});

describe('canShowOriginal', () => {
  it('PDFでページがあれば出す', () => expect(canShowOriginal('pdf', 3)).toBe(true));
  it('PPTXでも出す', () => expect(canShowOriginal('pptx', 1)).toBe(true));
  it('録音では出さない', () => expect(canShowOriginal('recording', 1)).toBe(false));
  it('テキストでは出さない', () => expect(canShowOriginal('text', 1)).toBe(false));
  it('ページ番号が無ければ出さない', () => {
    expect(canShowOriginal('pdf', null)).toBe(false);
    expect(canShowOriginal('pdf', undefined)).toBe(false);
  });
  it('kind不明なら出さない', () => expect(canShowOriginal(undefined, 1)).toBe(false));
});

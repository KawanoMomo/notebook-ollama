import { describe, expect, it, vi, beforeEach } from 'vitest';
import { createNoticesStore } from '$lib/stores/notices.svelte';
import type { Notice } from '$lib/api/types';

const STORAGE_KEY = 'seen_notice_ids';

function makeNotice(overrides: Partial<Notice> = {}): Notice {
  return {
    id: 'notice-1',
    date: '2026-06-28',
    title: 'お知らせ',
    body: '本文',
    subsections: null,
    ...overrides,
  };
}

function seedSeen(ids: string[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
}

function makeApi(items: Notice[] = []) {
  return {
    listNotices: vi.fn().mockResolvedValue(items),
  };
}

beforeEach(() => {
  // テスト間で localStorage が共有されるため毎回クリアして
  // 「シード無し」テストが他テストの seed を引き継がないようにする。
  localStorage.clear();
});

describe('notices store', () => {
  describe('localStorage 復元', () => {
    it('localStorage が空ならば seenIds は空集合で初期化される', () => {
      const store = createNoticesStore(makeApi() as never);
      expect(store.seenIds.size).toBe(0);
      expect(store.unreadCount).toBe(0);
    });

    it('localStorage に seed された ID 集合を復元する', () => {
      seedSeen(['n1', 'n2', 'n3']);
      const store = createNoticesStore(makeApi() as never);
      expect(store.seenIds.has('n1')).toBe(true);
      expect(store.seenIds.has('n2')).toBe(true);
      expect(store.seenIds.has('n3')).toBe(true);
      expect(store.seenIds.size).toBe(3);
    });

    it('localStorage に不正な JSON があっても空集合で初期化される (クラッシュしない)', () => {
      localStorage.setItem(STORAGE_KEY, '{not valid json');
      const store = createNoticesStore(makeApi() as never);
      expect(store.seenIds.size).toBe(0);
    });

    it('localStorage が配列以外を保持していた場合も空集合で初期化される', () => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ foo: 'bar' }));
      const store = createNoticesStore(makeApi() as never);
      expect(store.seenIds.size).toBe(0);
    });

    it('localStorage に文字列以外が混じっていたら string のみ採用する', () => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(['n1', 42, null, 'n2', { id: 'x' }]));
      const store = createNoticesStore(makeApi() as never);
      expect([...store.seenIds].sort()).toEqual(['n1', 'n2']);
    });

    it('CJK / emoji の ID もそのまま復元できる', () => {
      const cjk = 'お知らせ-2026-06-28';
      const emoji = 'notice-💥';
      seedSeen([cjk, emoji]);
      const store = createNoticesStore(makeApi() as never);
      expect(store.seenIds.has(cjk)).toBe(true);
      expect(store.seenIds.has(emoji)).toBe(true);
    });
  });

  describe('load()', () => {
    it('items を API から取得して反映する', async () => {
      const items = [makeNotice({ id: 'n1' }), makeNotice({ id: 'n2' })];
      const api = makeApi(items);
      const store = createNoticesStore(api as never);
      await store.load();
      expect(api.listNotices).toHaveBeenCalledTimes(1);
      expect(store.items).toEqual(items);
    });

    it('空レスポンスでも items=[]・unreadCount=0', async () => {
      const store = createNoticesStore(makeApi([]) as never);
      await store.load();
      expect(store.items).toEqual([]);
      expect(store.unreadCount).toBe(0);
    });
  });

  describe('unreadCount (derived)', () => {
    it('seenIds に含まれない notice の件数を返す', async () => {
      seedSeen(['n2']);
      const items = [makeNotice({ id: 'n1' }), makeNotice({ id: 'n2' }), makeNotice({ id: 'n3' })];
      const store = createNoticesStore(makeApi(items) as never);
      await store.load();
      expect(store.unreadCount).toBe(2);
    });

    it('全 notice が未読なら unreadCount = items.length', async () => {
      const items = [makeNotice({ id: 'a' }), makeNotice({ id: 'b' })];
      const store = createNoticesStore(makeApi(items) as never);
      await store.load();
      expect(store.unreadCount).toBe(2);
    });

    it('全 notice が既読なら unreadCount = 0', async () => {
      const items = [makeNotice({ id: 'a' }), makeNotice({ id: 'b' })];
      seedSeen(['a', 'b']);
      const store = createNoticesStore(makeApi(items) as never);
      await store.load();
      expect(store.unreadCount).toBe(0);
    });
  });

  describe('markSeen', () => {
    it('未読 ID を既読に追加し localStorage へ永続化する', async () => {
      const items = [makeNotice({ id: 'n1' }), makeNotice({ id: 'n2' })];
      const store = createNoticesStore(makeApi(items) as never);
      await store.load();
      expect(store.unreadCount).toBe(2);

      store.markSeen('n1');

      expect(store.seenIds.has('n1')).toBe(true);
      expect(store.unreadCount).toBe(1);

      const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]');
      expect(persisted).toContain('n1');
    });

    it('既に seen な ID への markSeen は no-op (冪等)', async () => {
      seedSeen(['n1']);
      const items = [makeNotice({ id: 'n1' })];
      const store = createNoticesStore(makeApi(items) as never);
      await store.load();

      const before = localStorage.getItem(STORAGE_KEY);
      store.markSeen('n1');
      const after = localStorage.getItem(STORAGE_KEY);

      expect(store.seenIds.size).toBe(1);
      expect(after).toBe(before); // 同一内容
    });

    it('複数の markSeen を直列に呼び出しても全て永続化される', async () => {
      const items = [
        makeNotice({ id: 'a' }),
        makeNotice({ id: 'b' }),
        makeNotice({ id: 'c' }),
      ];
      const store = createNoticesStore(makeApi(items) as never);
      await store.load();

      store.markSeen('a');
      store.markSeen('b');
      store.markSeen('c');

      const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]') as string[];
      expect(persisted.sort()).toEqual(['a', 'b', 'c']);
      expect(store.unreadCount).toBe(0);
    });

    it('別ストアを後から作ると localStorage 永続化を引き継ぐ', async () => {
      const items = [makeNotice({ id: 'n1' }), makeNotice({ id: 'n2' })];
      const store1 = createNoticesStore(makeApi(items) as never);
      await store1.load();
      store1.markSeen('n1');

      // 同じ localStorage を共有する新しいインスタンス (タブ再読込みを模倣)
      const store2 = createNoticesStore(makeApi(items) as never);
      await store2.load();
      expect(store2.seenIds.has('n1')).toBe(true);
      expect(store2.unreadCount).toBe(1);
    });

    it('CJK / emoji ID も markSeen して unreadCount に反映される', async () => {
      const items = [
        makeNotice({ id: 'お知らせ-1' }),
        makeNotice({ id: 'notice-💥' }),
      ];
      const store = createNoticesStore(makeApi(items) as never);
      await store.load();
      expect(store.unreadCount).toBe(2);

      store.markSeen('お知らせ-1');
      store.markSeen('notice-💥');
      expect(store.unreadCount).toBe(0);

      const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]') as string[];
      expect(persisted).toContain('お知らせ-1');
      expect(persisted).toContain('notice-💥');
    });

    it('items に存在しない ID への markSeen も seenIds には載るが unreadCount には影響しない', async () => {
      const items = [makeNotice({ id: 'a' })];
      const store = createNoticesStore(makeApi(items) as never);
      await store.load();

      store.markSeen('phantom');

      expect(store.seenIds.has('phantom')).toBe(true);
      expect(store.unreadCount).toBe(1); // a はまだ未読
    });
  });
});

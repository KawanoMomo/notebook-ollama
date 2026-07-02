/**
 * notices store — お知らせ一覧と既読 ID 管理。
 *
 * spec: docs/specs/2026-06-28-crash-report-feedback-hub-design.md §5.3 / §8.2
 * api : apps/web/src/lib/api/feedbackHub.ts (feedbackHubApi.listNotices)
 *
 * MVP では既読状態を FE 側 `localStorage["seen_notice_ids"]` に保持する
 * (spec §5.3 / types.ts UnreadCount 参照)。複数端末で同期されないが、
 * MVP のスコープでは許容している。
 *
 * Svelte 5 reactivity の都合上、`seenIds` は `Set` 参照を毎回 replace する
 * (`.add()` のような in-place mutation だと plain Set は notify されない)。
 *
 * SSR / prerender 時は `localStorage` が undefined のため、空集合で初期化
 * して永続化操作も no-op にする。
 */
import { feedbackHubApi } from '$lib/api/feedbackHub';
import type { Notice } from '$lib/api/types';

const STORAGE_KEY = 'seen_notice_ids';

type NoticesApi = Pick<typeof feedbackHubApi, 'listNotices'>;

export interface NoticesStore {
  readonly items: Notice[];
  readonly seenIds: ReadonlySet<string>;
  readonly unreadCount: number;
  load(): Promise<void>;
  markSeen(id: string): void;
}

function loadSeenIds(): Set<string> {
  if (typeof localStorage === 'undefined') return new Set();
  let raw: string | null;
  try {
    raw = localStorage.getItem(STORAGE_KEY);
  } catch {
    return new Set();
  }
  if (raw == null) return new Set();
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((x): x is string => typeof x === 'string'));
  } catch {
    return new Set();
  }
}

function persistSeenIds(set: ReadonlySet<string>): void {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...set]));
  } catch {
    // quota / private browsing — silently ignore: MVP では UX に響かせない
  }
}

export function createNoticesStore(api: NoticesApi = feedbackHubApi): NoticesStore {
  let items = $state<Notice[]>([]);
  let seenIds = $state<Set<string>>(loadSeenIds());
  const unreadCount = $derived(items.filter((n) => !seenIds.has(n.id)).length);

  return {
    get items() {
      return items;
    },
    get seenIds() {
      return seenIds;
    },
    get unreadCount() {
      return unreadCount;
    },
    async load() {
      items = await api.listNotices();
    },
    markSeen(id) {
      if (seenIds.has(id)) return; // 冪等: localStorage への余計な write も避ける
      const next = new Set(seenIds);
      next.add(id);
      seenIds = next;
      persistSeenIds(next);
    },
  };
}

export const noticesStore = createNoticesStore();

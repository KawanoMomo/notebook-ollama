/**
 * feedbackHub store — フィードバックハブ drawer の開閉/タブ状態と未読バッジ集計。
 *
 * spec: docs/specs/2026-06-28-crash-report-feedback-hub-design.md §8.2
 *
 * `unreadCount` は notices/crashReports サブストアの合計。
 * - notices.unreadCount: お知らせの未読件数 (localStorage の seenIds と照合)
 * - crashReports.pendingCount: 未送信クラッシュレポート件数
 *
 * サブストアは DI 可能 (テスト時は createNoticesStore() / createCrashReportsStore()
 * の新規インスタンスを渡してグローバル状態の漏れを防ぐ)。
 */
import { crashReportsStore, type CrashReportsStore } from './crashReports.svelte';
import { noticesStore, type NoticesStore } from './notices.svelte';

export type FeedbackHubTab = 'notices' | 'bugs' | 'feedback';

export interface FeedbackHubStore {
  readonly drawerOpen: boolean;
  readonly activeTab: FeedbackHubTab;
  readonly unreadCount: number;
  open(): void;
  close(): void;
  setTab(tab: FeedbackHubTab): void;
}

export function createFeedbackHubStore(
  notices: NoticesStore = noticesStore,
  crashes: CrashReportsStore = crashReportsStore,
): FeedbackHubStore {
  let drawerOpen = $state(false);
  let activeTab = $state<FeedbackHubTab>('notices');
  // 各サブストアの getter は内部 $state を read するため、$derived が依存追跡する。
  const unreadCount = $derived(notices.unreadCount + crashes.pendingCount);

  return {
    get drawerOpen() {
      return drawerOpen;
    },
    get activeTab() {
      return activeTab;
    },
    get unreadCount() {
      return unreadCount;
    },
    open() {
      drawerOpen = true;
    },
    close() {
      drawerOpen = false;
    },
    setTab(tab) {
      activeTab = tab;
    },
  };
}

export const feedbackHubStore = createFeedbackHubStore();

import { describe, expect, it, vi, beforeEach } from 'vitest';
import {
  createFeedbackHubStore,
  type FeedbackHubTab,
} from '$lib/stores/feedbackHub.svelte';
import { createNoticesStore } from '$lib/stores/notices.svelte';
import { createCrashReportsStore } from '$lib/stores/crashReports.svelte';
import type {
  CrashHardware,
  Notice,
  PendingCrash,
} from '$lib/api/types';

const HARDWARE_PLACEHOLDER: CrashHardware = {
  cpu_model: 'cpu',
  cpu_cores: 8,
  cpu_threads: 16,
  ram_total_gb: 32,
  ram_available_gb: 16,
  gpu_model: 'gpu',
  gpu_vram_mb: 1024,
  driver_version: '0',
  disk_free_gb: 100,
  os_platform: 'Windows-11',
  python_version: '3.12.0',
};

function makeNotice(overrides: Partial<Notice> = {}): Notice {
  return {
    id: 'n',
    date: '2026-06-28',
    title: 't',
    body: 'b',
    subsections: null,
    ...overrides,
  };
}

function makeCrash(overrides: Partial<PendingCrash> = {}): PendingCrash {
  return {
    id: 'c',
    fingerprint: 'fp',
    created_at: '2026-06-28T00:00:00Z',
    exception_type: 'RuntimeError',
    exception_message: 'boom',
    trace: [],
    hardware: HARDWARE_PLACEHOLDER,
    log_tail: [],
    source: 'fastapi',
    ...overrides,
  };
}

function makeNoticesApi(items: Notice[] = []) {
  return { listNotices: vi.fn().mockResolvedValue(items) };
}

function makeCrashApi(items: PendingCrash[] = []) {
  return {
    listPending: vi.fn().mockResolvedValue(items),
    dismiss: vi.fn().mockResolvedValue(undefined),
    markReported: vi.fn().mockResolvedValue(undefined),
  };
}

const ALL_TABS: FeedbackHubTab[] = ['notices', 'bugs', 'feedback'];

beforeEach(() => {
  // notices ストアが localStorage を読むため、テスト間で漏れないよう毎回クリア
  localStorage.clear();
});

describe('feedbackHub store', () => {
  describe('初期状態', () => {
    it('drawerOpen=false, activeTab="notices", unreadCount=0', () => {
      const notices = createNoticesStore(makeNoticesApi() as never);
      const crashes = createCrashReportsStore(makeCrashApi() as never);
      const hub = createFeedbackHubStore(notices, crashes);
      expect(hub.drawerOpen).toBe(false);
      expect(hub.activeTab).toBe('notices');
      expect(hub.unreadCount).toBe(0);
    });
  });

  describe('drawerOpen', () => {
    it('open() で true / close() で false に切り替わる', () => {
      const hub = createFeedbackHubStore(
        createNoticesStore(makeNoticesApi() as never),
        createCrashReportsStore(makeCrashApi() as never),
      );
      hub.open();
      expect(hub.drawerOpen).toBe(true);
      hub.close();
      expect(hub.drawerOpen).toBe(false);
    });

    it('open() を複数回呼んでも冪等で true のまま', () => {
      const hub = createFeedbackHubStore(
        createNoticesStore(makeNoticesApi() as never),
        createCrashReportsStore(makeCrashApi() as never),
      );
      hub.open();
      hub.open();
      expect(hub.drawerOpen).toBe(true);
    });

    it('close() を初期状態で呼んでもエラーにならない (false のまま)', () => {
      const hub = createFeedbackHubStore(
        createNoticesStore(makeNoticesApi() as never),
        createCrashReportsStore(makeCrashApi() as never),
      );
      hub.close();
      expect(hub.drawerOpen).toBe(false);
    });
  });

  describe('setTab — 全タブを網羅', () => {
    // lessons learned: enum は手で間引かず全網羅
    it.each(ALL_TABS)('setTab("%s") で activeTab が切り替わる', (tab) => {
      const hub = createFeedbackHubStore(
        createNoticesStore(makeNoticesApi() as never),
        createCrashReportsStore(makeCrashApi() as never),
      );
      hub.setTab(tab);
      expect(hub.activeTab).toBe(tab);
    });

    it('複数回 setTab を呼ぶと最後の値が反映される', () => {
      const hub = createFeedbackHubStore(
        createNoticesStore(makeNoticesApi() as never),
        createCrashReportsStore(makeCrashApi() as never),
      );
      hub.setTab('bugs');
      hub.setTab('feedback');
      hub.setTab('notices');
      expect(hub.activeTab).toBe('notices');
    });
  });

  describe('unreadCount — サブストアの合計', () => {
    it('notices.unreadCount + crashReports.pendingCount を返す', async () => {
      const noticeItems = [makeNotice({ id: 'n1' }), makeNotice({ id: 'n2' })]; // 全部未読 → 2
      const crashItems = [
        makeCrash({ id: 'c1' }),
        makeCrash({ id: 'c2' }),
        makeCrash({ id: 'c3' }),
      ]; // 3 件未送信
      const notices = createNoticesStore(makeNoticesApi(noticeItems) as never);
      const crashes = createCrashReportsStore(makeCrashApi(crashItems) as never);
      const hub = createFeedbackHubStore(notices, crashes);

      await notices.load();
      await crashes.load();

      expect(notices.unreadCount).toBe(2);
      expect(crashes.pendingCount).toBe(3);
      expect(hub.unreadCount).toBe(5);
    });

    it('markSeen で notices 側が減ると hub.unreadCount も減る', async () => {
      const noticeItems = [makeNotice({ id: 'n1' }), makeNotice({ id: 'n2' })];
      const notices = createNoticesStore(makeNoticesApi(noticeItems) as never);
      const crashes = createCrashReportsStore(makeCrashApi() as never);
      const hub = createFeedbackHubStore(notices, crashes);
      await notices.load();

      expect(hub.unreadCount).toBe(2);
      notices.markSeen('n1');
      expect(hub.unreadCount).toBe(1);
      notices.markSeen('n2');
      expect(hub.unreadCount).toBe(0);
    });

    it('dismiss で crashReports 側が減ると hub.unreadCount も減る', async () => {
      const crashItems = [makeCrash({ id: 'c1' }), makeCrash({ id: 'c2' })];
      const notices = createNoticesStore(makeNoticesApi() as never);
      const crashes = createCrashReportsStore(makeCrashApi(crashItems) as never);
      const hub = createFeedbackHubStore(notices, crashes);
      await crashes.load();

      expect(hub.unreadCount).toBe(2);
      await crashes.dismiss('c1');
      expect(hub.unreadCount).toBe(1);
      await crashes.markReported('c2');
      expect(hub.unreadCount).toBe(0);
    });

    it('両サブストアが空のとき unreadCount=0', () => {
      const hub = createFeedbackHubStore(
        createNoticesStore(makeNoticesApi() as never),
        createCrashReportsStore(makeCrashApi() as never),
      );
      expect(hub.unreadCount).toBe(0);
    });
  });

  describe('インスタンス独立性 (グローバル漏洩なし)', () => {
    it('別 hub インスタンスはそれぞれ独立した drawerOpen/activeTab を持つ', () => {
      const hubA = createFeedbackHubStore(
        createNoticesStore(makeNoticesApi() as never),
        createCrashReportsStore(makeCrashApi() as never),
      );
      const hubB = createFeedbackHubStore(
        createNoticesStore(makeNoticesApi() as never),
        createCrashReportsStore(makeCrashApi() as never),
      );

      hubA.open();
      hubA.setTab('bugs');

      expect(hubB.drawerOpen).toBe(false);
      expect(hubB.activeTab).toBe('notices');
    });
  });
});

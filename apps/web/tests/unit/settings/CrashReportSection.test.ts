/**
 * CrashReportSection — 設定画面「クラッシュレポート」セクション (Sprint 7 Task 7.2)
 *
 * spec : docs/specs/2026-06-28-crash-report-feedback-hub-design.md §5.8
 * plan : docs/superpowers/plans/2026-06-28-crash-report-feedback-hub.md Task 7.2
 *
 * テスト方針:
 * - DI 可能 (`settings` / `hub` / `crashes` props) なので、テストごとに
 *   factory で作った独立インスタンスを渡してグローバル singleton の状態漏れを避ける。
 * - NEW バッジは localStorage の `crashreport_nav_seen` フラグで制御するため
 *   各テストで localStorage.clear() してから検証する。
 *
 * Sprint 5 教訓: vitest GREEN だけでは不十分。本 sprint の視覚ゲートで
 * Playwright によるスクショ確認が別途必要なため、本ファイルでは「結線が正しい
 * (handler が呼ばれる、props が反映される、store のメソッド経由で I/O が走る)」
 * を中心に検証する。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';

import CrashReportSection from '$lib/components/settings/CrashReportSection.svelte';
import {
  createSettingsStore,
  type SettingsStore,
} from '$lib/stores/settings.svelte';
import {
  createFeedbackHubStore,
  type FeedbackHubStore,
} from '$lib/stores/feedbackHub.svelte';
import {
  createCrashReportsStore,
  type CrashReportsStore,
} from '$lib/stores/crashReports.svelte';
import { createNoticesStore } from '$lib/stores/notices.svelte';
import type {
  AppSettings,
  CrashReportSettings,
  PendingCrash,
  Stats,
} from '$lib/api/types';

const NAV_SEEN_KEY = 'crashreport_nav_seen';

const BASE_AUDIO = {
  mic_device_index: null,
  system_device_index: null,
  whisper_model: 'base',
  device: 'cpu' as const,
  compute_type: 'int8' as const,
  live_caption_default: true,
  agc_enabled: true,
  diarization_enabled: false,
  max_speakers: null,
  voiceprint_naming: false,
  name_inference_llm: false,
  name_threshold: 0.5,
  storage_format: 'aac' as const,
  storage_bitrate_kbps: 64,
  keep_audio: true,
  auto_title: false,
};

function makeAppSettings(crash_report: CrashReportSettings | undefined): AppSettings {
  return {
    ollama: {
      endpoint: 'http://localhost:11434',
      default_model: 'qwen2.5:14b',
      embedding_model: 'nomic-embed-text',
      embedding_dim: 768,
      request_timeout_seconds: 600,
      chat_read_timeout_seconds: 600,
      vision_model: '',
    },
    generation: { context_budget_ratio: 0.8, response_budget_tokens: 1024, auto_continue_max: 0 },
    retrieval: { top_k: 8, top_k_max: 30, min_history_turns: 2 },
    audio: BASE_AUDIO,
    crash_report,
    visual: { embedding_model: '', search_enabled: true },
  };
}

function makeStats(): Stats {
  return { notebook_count: 0, source_count: 0, chunk_count: 0, data_dir: '/tmp' };
}

interface SettingsApiStub {
  get: ReturnType<typeof vi.fn>;
  stats: ReturnType<typeof vi.fn>;
  putAudio: ReturnType<typeof vi.fn>;
  putOllama: ReturnType<typeof vi.fn>;
  switchEmbedding: ReturnType<typeof vi.fn>;
  putCrashReport: ReturnType<typeof vi.fn>;
}

function makeSettingsApi(opts: {
  crash_report?: CrashReportSettings | undefined;
  putResult?: CrashReportSettings;
} = {}): SettingsApiStub {
  const initial = opts.crash_report;
  return {
    get: vi.fn().mockResolvedValue(makeAppSettings(initial)),
    stats: vi.fn().mockResolvedValue(makeStats()),
    putAudio: vi.fn(),
    putOllama: vi.fn(),
    switchEmbedding: vi.fn(),
    putCrashReport: vi
      .fn()
      .mockImplementation(async (patch: Partial<CrashReportSettings>) => {
        const base: CrashReportSettings = initial ?? {
          enabled: null,
          auto_prompt: true,
          opted_in_at: null,
        };
        return opts.putResult ?? { ...base, ...patch };
      }),
  };
}

function makeCrashApi(pending: PendingCrash[] = []) {
  return {
    listPending: vi.fn().mockResolvedValue(pending),
    dismiss: vi.fn().mockResolvedValue(undefined),
    markReported: vi.fn().mockResolvedValue(undefined),
  };
}

function makeHub(crashes: CrashReportsStore): FeedbackHubStore {
  return createFeedbackHubStore(
    createNoticesStore({ listNotices: vi.fn().mockResolvedValue([]) } as never),
    crashes,
  );
}

function makePending(overrides: Partial<PendingCrash> = {}): PendingCrash {
  return {
    id: 'pc',
    fingerprint: 'fp',
    created_at: '2026-06-28T00:00:00Z',
    exception_type: 'RuntimeError',
    exception_message: 'boom',
    trace: [],
    hardware: {},
    log_tail: [],
    source: 'fastapi',
    ...overrides,
  };
}

async function setup(opts: {
  crash_report?: CrashReportSettings | undefined;
  pending?: PendingCrash[];
  putResult?: CrashReportSettings;
} = {}) {
  const api = makeSettingsApi({
    crash_report: opts.crash_report,
    putResult: opts.putResult,
  });
  const settings: SettingsStore = createSettingsStore(api as never);
  await settings.load();

  const crashApi = makeCrashApi(opts.pending ?? []);
  const crashes = createCrashReportsStore(crashApi as never);
  if ((opts.pending ?? []).length > 0) {
    await crashes.load();
  }
  const hub = makeHub(crashes);
  return { settings, hub, crashes, api, crashApi };
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => cleanup());

// ---------------------------------------------------------------------------
// 描画 — 見出し / 説明文 / 4 つの行
// ---------------------------------------------------------------------------

describe('CrashReportSection — 描画', () => {
  it('見出し「クラッシュレポート」と説明文を描画する', async () => {
    const { settings, hub, crashes } = await setup();
    render(CrashReportSection, { settings, hub, crashes });
    expect(screen.getByRole('heading', { name: /クラッシュレポート/ })).toBeDefined();
    expect(
      screen.getByText(/エラー発生時、GitHubに不具合を報告できる機能です/),
    ).toBeDefined();
  });

  it('4 つの行ラベルを全て描画する', async () => {
    const { settings, hub, crashes } = await setup();
    render(CrashReportSection, { settings, hub, crashes });
    // 行ラベルは exact match で 1 件ずつ存在することを担保 (小文字の補助説明文
    // にも同じ単語が含まれているため、部分一致を使うと複数 match で失敗する)。
    expect(
      screen.getByText('クラッシュレポート機能を有効にする', { exact: true }),
    ).toBeDefined();
    expect(
      screen.getByText('エラー発生時に自動でダイアログを表示', { exact: true }),
    ).toBeDefined();
    expect(screen.getByText('未送信レポート', { exact: true })).toBeDefined();
    expect(
      screen.getByText('サンプルレポートを見る', { exact: true }),
    ).toBeDefined();
  });
});

// ---------------------------------------------------------------------------
// Row 1: enabled toggle
// ---------------------------------------------------------------------------

describe('CrashReportSection — Row 1: enabled toggle', () => {
  it('settings.crash_report.enabled が未設定 (undefined / null) のとき OFF として描画される', async () => {
    const { settings, hub, crashes } = await setup({ crash_report: undefined });
    render(CrashReportSection, { settings, hub, crashes });
    const sw = screen.getByRole('switch', {
      name: /クラッシュレポート機能を有効にする/,
    });
    expect(sw.getAttribute('aria-checked')).toBe('false');
  });

  it('enabled=true のとき ON として描画される', async () => {
    const { settings, hub, crashes } = await setup({
      crash_report: { enabled: true, auto_prompt: true, opted_in_at: null },
    });
    render(CrashReportSection, { settings, hub, crashes });
    const sw = screen.getByRole('switch', {
      name: /クラッシュレポート機能を有効にする/,
    });
    expect(sw.getAttribute('aria-checked')).toBe('true');
  });

  it('クリックで settings.putCrashReport({ enabled: true }) が呼ばれる (null → true)', async () => {
    const { settings, hub, crashes, api } = await setup({
      crash_report: { enabled: null, auto_prompt: true, opted_in_at: null },
      putResult: {
        enabled: true,
        auto_prompt: true,
        opted_in_at: '2026-06-28T00:00:00Z',
      },
    });
    render(CrashReportSection, { settings, hub, crashes });
    const sw = screen.getByRole('switch', {
      name: /クラッシュレポート機能を有効にする/,
    });
    await fireEvent.click(sw);
    await waitFor(() => expect(api.putCrashReport).toHaveBeenCalledTimes(1));
    expect(api.putCrashReport).toHaveBeenCalledWith(
      expect.objectContaining({ enabled: true }),
    );
    // store 側も更新される
    await waitFor(() => expect(settings.crashReport.enabled).toBe(true));
  });

  it('クリックで true → false へ切り替わる', async () => {
    const { settings, hub, crashes, api } = await setup({
      crash_report: { enabled: true, auto_prompt: true, opted_in_at: null },
      putResult: { enabled: false, auto_prompt: true, opted_in_at: null },
    });
    render(CrashReportSection, { settings, hub, crashes });
    const sw = screen.getByRole('switch', {
      name: /クラッシュレポート機能を有効にする/,
    });
    await fireEvent.click(sw);
    await waitFor(() =>
      expect(api.putCrashReport).toHaveBeenCalledWith(
        expect.objectContaining({ enabled: false }),
      ),
    );
  });
});

// ---------------------------------------------------------------------------
// Row 2: auto_prompt toggle (independent of enabled)
// ---------------------------------------------------------------------------

describe('CrashReportSection — Row 2: auto_prompt toggle', () => {
  it('auto_prompt=true のとき ON として描画される', async () => {
    const { settings, hub, crashes } = await setup({
      crash_report: { enabled: false, auto_prompt: true, opted_in_at: null },
    });
    render(CrashReportSection, { settings, hub, crashes });
    const sw = screen.getByRole('switch', {
      name: /エラー発生時に自動でダイアログを表示/,
    });
    expect(sw.getAttribute('aria-checked')).toBe('true');
  });

  it('enabled=false でも auto_prompt は独立してトグルできる', async () => {
    const { settings, hub, crashes, api } = await setup({
      crash_report: { enabled: false, auto_prompt: true, opted_in_at: null },
      putResult: { enabled: false, auto_prompt: false, opted_in_at: null },
    });
    render(CrashReportSection, { settings, hub, crashes });
    const sw = screen.getByRole('switch', {
      name: /エラー発生時に自動でダイアログを表示/,
    });
    await fireEvent.click(sw);
    await waitFor(() =>
      expect(api.putCrashReport).toHaveBeenCalledWith(
        expect.objectContaining({ enabled: false, auto_prompt: false }),
      ),
    );
  });

  it('auto_prompt のクリックで enabled は変えない', async () => {
    const { settings, hub, crashes, api } = await setup({
      crash_report: { enabled: true, auto_prompt: true, opted_in_at: null },
      putResult: {
        enabled: true,
        auto_prompt: false,
        opted_in_at: null,
      },
    });
    render(CrashReportSection, { settings, hub, crashes });
    const sw = screen.getByRole('switch', {
      name: /エラー発生時に自動でダイアログを表示/,
    });
    await fireEvent.click(sw);
    await waitFor(() => expect(api.putCrashReport).toHaveBeenCalled());
    const callArg = api.putCrashReport.mock.calls[0][0];
    expect(callArg.enabled).toBe(true); // 変えていない
    expect(callArg.auto_prompt).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Row 3: 未送信件数 + 「確認 →」
// ---------------------------------------------------------------------------

describe('CrashReportSection — Row 3: 未送信レポート', () => {
  it('crashReportsStore.pendingCount を badge として描画する', async () => {
    const { settings, hub, crashes } = await setup({
      pending: [makePending({ id: 'a' }), makePending({ id: 'b' })],
    });
    render(CrashReportSection, { settings, hub, crashes });
    // badge は数値テキストで pendingCount を出す
    await waitFor(() => {
      const badge = screen.getByTestId('crash-pending-badge');
      expect(badge.textContent?.trim()).toBe('2');
    });
  });

  it('「確認 →」クリックで hub.setTab("bugs") + hub.open() を呼ぶ', async () => {
    const { settings, hub, crashes } = await setup({
      pending: [makePending({ id: 'a' })],
    });
    const setTabSpy = vi.spyOn(hub, 'setTab');
    const openSpy = vi.spyOn(hub, 'open');
    render(CrashReportSection, { settings, hub, crashes });
    const btn = screen.getByRole('button', { name: /^確認/ });
    await fireEvent.click(btn);
    expect(setTabSpy).toHaveBeenCalledWith('bugs');
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(hub.activeTab).toBe('bugs');
    expect(hub.drawerOpen).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Row 4: 「プレビューを開く」 (サンプル PendingCrash)
// ---------------------------------------------------------------------------

describe('CrashReportSection — Row 4: サンプルプレビュー', () => {
  it('「プレビューを開く」クリックで crashes.showPreview に PendingCrash を渡す', async () => {
    const { settings, hub, crashes } = await setup();
    const spy = vi.spyOn(crashes, 'showPreview');
    render(CrashReportSection, { settings, hub, crashes });
    const btn = screen.getByRole('button', { name: /プレビューを開く/ });
    await fireEvent.click(btn);
    expect(spy).toHaveBeenCalledTimes(1);
    const arg = spy.mock.calls[0][0];
    // PendingCrash 形状の必須フィールドが揃っている
    expect(arg.id).toBeTruthy();
    expect(arg.fingerprint).toBeTruthy();
    expect(arg.exception_type).toBeTruthy();
    expect(arg.exception_message).toBeTruthy();
    expect(Array.isArray(arg.trace)).toBe(true);
    expect(typeof arg.hardware).toBe('object');
    expect(Array.isArray(arg.log_tail)).toBe(true);
    expect(arg.source).toBeTruthy();
  });

  it('「プレビューを開く」を 2 回呼んでも store の previewing は最後の sample を保持する', async () => {
    const { settings, hub, crashes } = await setup();
    render(CrashReportSection, { settings, hub, crashes });
    const btn = screen.getByRole('button', { name: /プレビューを開く/ });
    await fireEvent.click(btn);
    await fireEvent.click(btn);
    expect(crashes.previewing).not.toBeNull();
    expect(crashes.previewing?.id).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// NEW バッジ (初回表示のみ; localStorage 'crashreport_nav_seen')
// ---------------------------------------------------------------------------

describe('CrashReportSection — NEW バッジ', () => {
  it('localStorage に crashreport_nav_seen が無いとき NEW バッジを描画する', async () => {
    const { settings, hub, crashes } = await setup();
    render(CrashReportSection, { settings, hub, crashes });
    const badge = screen.queryByText(/NEW/);
    expect(badge).not.toBeNull();
  });

  it('初回 mount 後は localStorage.crashreport_nav_seen が立つ', async () => {
    const { settings, hub, crashes } = await setup();
    render(CrashReportSection, { settings, hub, crashes });
    await waitFor(() => {
      expect(localStorage.getItem(NAV_SEEN_KEY)).not.toBeNull();
    });
  });

  it('localStorage に既に crashreport_nav_seen がある場合は NEW バッジを描画しない', async () => {
    localStorage.setItem(NAV_SEEN_KEY, '1');
    const { settings, hub, crashes } = await setup();
    render(CrashReportSection, { settings, hub, crashes });
    expect(screen.queryByText(/NEW/)).toBeNull();
  });
});

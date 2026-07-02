/**
 * BugReportTab — 不具合タブ (Sprint 7 Task 7.1)
 *
 * spec: docs/specs/2026-06-28-crash-report-feedback-hub-design.md §5.4
 * plan: docs/superpowers/plans/2026-06-28-crash-report-feedback-hub.md Task 7.1
 *
 * 検証観点:
 * - 空リスト時は「未送信のレポート」見出しを出さず、「新規報告作成」カードのみ。
 * - 2 件 pending → 2 行 + 「新規報告作成」カード。
 * - 各行の「却下」→ store.dismiss(id) 呼び出し、行が消える。
 * - 各行の「プレビュー →」→ store.showPreview(crash) 呼び出し。
 * - 「+ 新規報告を作成」→ store.showPreview(空 PendingCrash) 呼び出し。
 * - mount 時に items が空なら store.load() を呼ぶ。
 * - loading / error 状態の描画。
 *
 * Sprint 5 lessons (per parent agent):
 * - vitest 単体 GREEN だけでは Playwright で 5 件の wiring/visual 欠陥が出た。
 *   そのため、本テストでは store の reactivity (dismiss → 行消失) と
 *   showPreview 呼び出しの実体 (crash オブジェクトのフィールド) を厳密に検証する。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import BugReportTab from '$lib/components/feedback-hub/BugReportTab.svelte';
import { createCrashReportsStore } from '$lib/stores/crashReports.svelte';
import type { CrashHardware, PendingCrash } from '$lib/api/types';

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

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

function makeCrash(overrides: Partial<PendingCrash> = {}): PendingCrash {
  return {
    id: 'c1',
    fingerprint: 'fp1',
    created_at: '2026-06-28T00:00:00Z',
    exception_type: 'RuntimeError',
    exception_message: 'boom happened',
    trace: ['  File "app.py", line 42, in handler', '  RuntimeError: boom happened'],
    hardware: HARDWARE_PLACEHOLDER,
    log_tail: [],
    source: 'fastapi',
    ...overrides,
  };
}

function makeApi(items: PendingCrash[] = []) {
  return {
    listPending: vi.fn().mockResolvedValue(items),
    dismiss: vi.fn().mockResolvedValue(undefined),
    markReported: vi.fn().mockResolvedValue(undefined),
  };
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: Error) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => cleanup());

// ---------------------------------------------------------------------------
// header description + headings
// ---------------------------------------------------------------------------

describe('BugReportTab — 冒頭説明文', () => {
  it('説明文「アプリで発生したエラーを開発者に報告できます。送信前にプレビューで内容を確認・編集できます。」が出る', async () => {
    const store = createCrashReportsStore(makeApi([]) as never);
    render(BugReportTab, { store });
    await waitFor(() => {
      expect(
        screen.getByText(
          /アプリで発生したエラーを開発者に報告できます。送信前にプレビューで内容を確認・編集できます。/,
        ),
      ).toBeDefined();
    });
  });
});

// ---------------------------------------------------------------------------
// 空リスト
// ---------------------------------------------------------------------------

describe('BugReportTab — empty list', () => {
  it('mount 時に items が空なら store.load() を呼ぶ', async () => {
    const api = makeApi([]);
    const store = createCrashReportsStore(api as never);
    render(BugReportTab, { store });
    await waitFor(() => expect(api.listPending).toHaveBeenCalledTimes(1));
  });

  it('既に items がロード済みなら mount 時に load() を呼ばない', async () => {
    const api = makeApi([makeCrash({ id: 'pre' })]);
    const store = createCrashReportsStore(api as never);
    await store.load(); // 事前ロード
    api.listPending.mockClear();
    render(BugReportTab, { store });
    await new Promise((r) => setTimeout(r, 30));
    expect(api.listPending).not.toHaveBeenCalled();
  });

  it('空リスト時も「未送信のレポート」見出しを常に表示する', async () => {
    // 視覚評価フィードバック: heading が #if pending>0 内にしかなかったため、
    // 空状態でセクションが消えてユーザに「何が空なのか」が伝わらなかった。
    // 見出しは常時表示する。
    const store = createCrashReportsStore(makeApi([]) as never);
    render(BugReportTab, { store });
    await waitFor(() => {
      // 「新規報告作成」カードが出ている = empty 経路に入っている
      expect(screen.getByRole('button', { name: /新規報告を作成/ })).toBeDefined();
    });
    expect(screen.getByText('未送信のレポート')).toBeDefined();
  });

  it('空リスト時は「未送信のレポートはありません」案内を出す', async () => {
    // 視覚評価フィードバック: 空状態の説明文がないと、ロード完了か未完了かの
    // 区別がつかない (新規報告カードだけが宙に浮く印象)。
    const store = createCrashReportsStore(makeApi([]) as never);
    const { container } = render(BugReportTab, { store });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /新規報告を作成/ })).toBeDefined();
    });
    expect(screen.getByText('未送信のレポートはありません')).toBeDefined();
    // small caption color = #6b7280 を満たす CSS クラス .empty-notice を付与
    const empty = container.querySelector('.empty-notice') as HTMLElement | null;
    expect(empty).not.toBeNull();
    expect(empty?.textContent).toMatch(/未送信のレポートはありません/);
  });

  it('空リスト時は crash-row が 1 件も無く「+ 新規報告を作成」カードが残る', async () => {
    const store = createCrashReportsStore(makeApi([]) as never);
    const { container } = render(BugReportTab, { store });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /新規報告を作成/ })).toBeDefined();
    });
    // crash row が 1 件も無いことを確認 (data-testid="crash-row" を使う)
    expect(container.querySelectorAll('[data-testid="crash-row"]').length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// 非空リスト
// ---------------------------------------------------------------------------

describe('BugReportTab — non-empty list', () => {
  it('2 件 pending → 2 行描画 + 「新規報告作成」カード', async () => {
    const items = [
      makeCrash({ id: 'a', exception_type: 'ValueError', exception_message: 'bad value' }),
      makeCrash({ id: 'b', exception_type: 'KeyError', exception_message: 'missing key' }),
    ];
    const store = createCrashReportsStore(makeApi(items) as never);
    const { container } = render(BugReportTab, { store });
    await waitFor(() => {
      expect(container.querySelectorAll('[data-testid="crash-row"]').length).toBe(2);
    });
    expect(screen.getByText('未送信のレポート')).toBeDefined();
    expect(screen.getByText('ValueError')).toBeDefined();
    expect(screen.getByText('KeyError')).toBeDefined();
    expect(screen.getByRole('button', { name: /新規報告を作成/ })).toBeDefined();
  });

  it('各行に exception_type / exception_message / trace 1行目 / created_at が出る', async () => {
    const item = makeCrash({
      id: 'x',
      exception_type: 'RuntimeError',
      exception_message: 'kaboom',
      trace: ['  File "core/foo.py", line 12, in bar', 'RuntimeError: kaboom'],
      created_at: '2026-06-28T10:30:00Z',
    });
    const store = createCrashReportsStore(makeApi([item]) as never);
    render(BugReportTab, { store });
    await waitFor(() => {
      expect(screen.getByText('RuntimeError')).toBeDefined();
    });
    expect(screen.getByText(/kaboom/)).toBeDefined();
    expect(screen.getByText(/core\/foo.py/)).toBeDefined();
    // created_at は ISO 由来の何らかの表示が出る
    expect(screen.getByText(/2026/)).toBeDefined();
  });

  it('created_at は UTC ISO ではなくユーザ locale (ja-JP) 表記で表示する', async () => {
    // 視覚評価フィードバック: 「2026-06-28 10:30」のような UTC 切り出しではなく、
    // ユーザの実時刻に変換して表示する (toLocaleString('ja-JP'))。
    // jsdom の TZ 環境差を避けるため、テスト内でも同じ Date#toLocaleString
    // で期待値を生成して一致を確認する (= 「ISO を素のまま slice しないこと」を保証)。
    const iso = '2026-06-28T10:30:00Z';
    const expected = new Date(iso).toLocaleString('ja-JP');
    const item = makeCrash({ id: 'tz', created_at: iso });
    const store = createCrashReportsStore(makeApi([item]) as never);
    render(BugReportTab, { store });
    await waitFor(() => {
      expect(screen.getByText('RuntimeError')).toBeDefined();
    });
    expect(screen.getByText(expected)).toBeDefined();
    // 旧 formatDate の `2026-06-28 10:30` 形式 (T/Z を切ったまま UTC) は出ない。
    expect(screen.queryByText('2026-06-28 10:30')).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 却下ボタン
// ---------------------------------------------------------------------------

describe('BugReportTab — 却下', () => {
  it('「却下」クリックで store.dismiss(id) が呼ばれる', async () => {
    const api = makeApi([makeCrash({ id: 'doomed' })]);
    const store = createCrashReportsStore(api as never);
    render(BugReportTab, { store });

    await waitFor(() => expect(screen.getByText('RuntimeError')).toBeDefined());
    const dismissBtn = screen.getByRole('button', { name: /却下/ });
    await fireEvent.click(dismissBtn);

    await waitFor(() => expect(api.dismiss).toHaveBeenCalledWith('doomed'));
  });

  it('却下後に行が消える', async () => {
    const api = makeApi([
      makeCrash({ id: 'keep', exception_type: 'ValueError' }),
      makeCrash({ id: 'doomed', exception_type: 'KeyError' }),
    ]);
    const store = createCrashReportsStore(api as never);
    const { container } = render(BugReportTab, { store });

    await waitFor(() => {
      expect(container.querySelectorAll('[data-testid="crash-row"]').length).toBe(2);
    });

    // 2件目 ("doomed") の却下ボタンをクリック
    const rows = container.querySelectorAll('[data-testid="crash-row"]');
    const doomedRow = rows[1] as HTMLElement;
    const dismissBtn = doomedRow.querySelector(
      'button[data-action="dismiss"]',
    ) as HTMLButtonElement;
    expect(dismissBtn).not.toBeNull();
    await fireEvent.click(dismissBtn);

    await waitFor(() => {
      expect(container.querySelectorAll('[data-testid="crash-row"]').length).toBe(1);
    });
    expect(screen.queryByText('KeyError')).toBeNull();
    expect(screen.getByText('ValueError')).toBeDefined();
  });
});

// ---------------------------------------------------------------------------
// プレビュー
// ---------------------------------------------------------------------------

describe('BugReportTab — プレビュー', () => {
  it('「プレビュー →」クリックで store.showPreview(crash) が呼ばれる', async () => {
    const crash = makeCrash({ id: 'preview-me' });
    const store = createCrashReportsStore(makeApi([crash]) as never);
    const spy = vi.spyOn(store, 'showPreview');
    render(BugReportTab, { store });

    await waitFor(() => expect(screen.getByText('RuntimeError')).toBeDefined());
    const previewBtn = screen.getByRole('button', { name: /プレビュー/ });
    await fireEvent.click(previewBtn);

    expect(spy).toHaveBeenCalledTimes(1);
    const arg = spy.mock.calls[0][0];
    expect(arg.id).toBe('preview-me');
    expect(arg.exception_type).toBe('RuntimeError');
  });

  it('プレビュー後に store.previewing が当該 crash に切り替わる', async () => {
    const crash = makeCrash({ id: 'p' });
    const store = createCrashReportsStore(makeApi([crash]) as never);
    render(BugReportTab, { store });

    await waitFor(() => expect(screen.getByText('RuntimeError')).toBeDefined());
    await fireEvent.click(screen.getByRole('button', { name: /プレビュー/ }));

    await waitFor(() => expect(store.previewing?.id).toBe('p'));
  });
});

// ---------------------------------------------------------------------------
// 手動新規報告
// ---------------------------------------------------------------------------

describe('BugReportTab — 手動新規報告', () => {
  it('「+ 新規報告を作成」→ store.showPreview に空 PendingCrash が渡される', async () => {
    const store = createCrashReportsStore(makeApi([]) as never);
    const spy = vi.spyOn(store, 'showPreview');
    render(BugReportTab, { store });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /新規報告を作成/ })).toBeDefined();
    });
    await fireEvent.click(screen.getByRole('button', { name: /新規報告を作成/ }));

    expect(spy).toHaveBeenCalledTimes(1);
    const arg = spy.mock.calls[0][0];
    expect(arg.id).toMatch(/^manual-/);
    expect(arg.fingerprint).toBe('');
    expect(arg.exception_type).toBe('');
    expect(arg.exception_message).toBe('');
    expect(arg.trace).toEqual([]);
    expect(arg.hardware).toEqual({});
    expect(arg.log_tail).toEqual([]);
    expect(arg.source).toBe('frontend');
    // created_at は ISO 文字列
    expect(typeof arg.created_at).toBe('string');
    expect(arg.created_at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });
});

// ---------------------------------------------------------------------------
// loading / error
// ---------------------------------------------------------------------------

describe('BugReportTab — loading state', () => {
  it('items=[] かつ load() 進行中はスピナー (role=status) を出す', async () => {
    const d = deferred<PendingCrash[]>();
    const api = {
      listPending: vi.fn().mockReturnValue(d.promise),
      dismiss: vi.fn(),
      markReported: vi.fn(),
    };
    const store = createCrashReportsStore(api as never);
    render(BugReportTab, { store });

    await waitFor(() => expect(screen.getByRole('status')).toBeDefined());
    d.resolve([]); // テスト後始末
  });
});

describe('BugReportTab — error state', () => {
  it('load() が reject したら「クラッシュレポートの取得に失敗しました」を出す', async () => {
    const api = {
      listPending: vi.fn().mockRejectedValue(new Error('network down')),
      dismiss: vi.fn(),
      markReported: vi.fn(),
    };
    const store = createCrashReportsStore(api as never);
    render(BugReportTab, { store });

    await waitFor(() =>
      expect(screen.getByText(/クラッシュレポートの取得に失敗しました/)).toBeDefined(),
    );
    expect(screen.getByRole('button', { name: /再試行/ })).toBeDefined();
  });

  it('再試行ボタンで listPending が再度呼ばれ、成功すれば行が出る', async () => {
    const api = {
      listPending: vi
        .fn()
        .mockRejectedValueOnce(new Error('network down'))
        .mockResolvedValueOnce([makeCrash({ id: 'after-retry' })]),
      dismiss: vi.fn(),
      markReported: vi.fn(),
    };
    const store = createCrashReportsStore(api as never);
    render(BugReportTab, { store });

    await waitFor(() =>
      expect(screen.getByText(/クラッシュレポートの取得に失敗しました/)).toBeDefined(),
    );
    await fireEvent.click(screen.getByRole('button', { name: /再試行/ }));

    await waitFor(() => expect(screen.getByText('RuntimeError')).toBeDefined());
    expect(api.listPending).toHaveBeenCalledTimes(2);
  });
});

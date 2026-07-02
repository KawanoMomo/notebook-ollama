/**
 * CrashDetectionModal のユニットテスト。
 *
 * 設計: docs/specs/2026-06-28-crash-report-feedback-hub-design.md §5.6
 * plan: docs/superpowers/plans/2026-06-28-crash-report-feedback-hub.md Task 5.6
 *
 * - フロント errorBoundary が新規例外を捕捉した瞬間に表示される即時モーダル。
 * - 「送信される/されない」の宣言文を **絶対に** UI に出さない
 *   ([[feedback-no-data-guarantee-in-ui]])。
 * - 「今は送らない」明示クリック必須 → 背景クリックでは閉じない。
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import CrashDetectionModal from '$lib/components/CrashDetectionModal.svelte';
import { createCrashReportsStore } from '$lib/stores/crashReports.svelte';
import type { PendingCrash } from '$lib/api/types';

afterEach(() => cleanup());

function makeCrash(overrides: Partial<PendingCrash> = {}): PendingCrash {
  return {
    id: 'crash-1',
    fingerprint: 'fp-abc',
    created_at: '2026-06-28T00:00:00Z',
    exception_type: 'RuntimeError',
    exception_message: 'boom',
    trace: [],
    hardware: {
      cpu_model: 'Intel(R) Core(TM) i9-12900KF',
      cpu_cores: 16,
      cpu_threads: 24,
      ram_total_gb: 32,
      ram_available_gb: 16,
      gpu_model: 'NVIDIA GeForce RTX 2080 Ti',
      gpu_vram_mb: 11264,
      driver_version: '555.42',
      disk_free_gb: 256,
      os_platform: 'Windows-11',
      python_version: '3.12',
    },
    log_tail: [],
    source: 'frontend',
    ...overrides,
  };
}

function baseProps(crash: PendingCrash, extra: Record<string, unknown> = {}) {
  return {
    crash,
    onDismiss: vi.fn(),
    onPreview: vi.fn(),
    ...extra,
  };
}

describe('CrashDetectionModal — rendering', () => {
  it('renders the warning header text (⚠ エラーが発生しました)', () => {
    render(CrashDetectionModal, baseProps(makeCrash()));
    const heading = screen.getByRole('heading', { name: /エラーが発生しました/ });
    expect(heading).toBeTruthy();
    expect(heading.textContent ?? '').toContain('エラーが発生しました');
  });

  it('renders the exception summary (type + message)', () => {
    render(
      CrashDetectionModal,
      baseProps(
        makeCrash({
          exception_type: 'ValueError',
          exception_message: 'unexpected input',
        }),
      ),
    );
    const summary = screen.getByTestId('crash-summary');
    expect(summary.textContent).toContain('ValueError');
    expect(summary.textContent).toContain('unexpected input');
  });

  it('renders the exception summary as a monospace block (<pre>)', () => {
    const { container } = render(CrashDetectionModal, baseProps(makeCrash()));
    const summary = container.querySelector(
      '[data-testid="crash-summary"]',
    ) as HTMLElement | null;
    expect(summary).not.toBeNull();
    // spec §5.6: monospace 12px + border-left: 3px solid #ef4444
    // jsdom may not compute styles; structural <pre> guarantees pre-wrap.
    expect(summary!.tagName).toBe('PRE');
  });

  it('renders the neutral preview-guidance text', () => {
    const { container } = render(CrashDetectionModal, baseProps(makeCrash()));
    const text = container.textContent ?? '';
    expect(text).toContain('次の画面で送信内容のプレビューが表示されます');
    expect(text).toContain('内容を確認・編集してから送信できます');
  });

  it.each([
    ['送信されます'],
    ['送信されません'],
    ['以下のデータが送信'],
    ['送信される情報'],
    ['送信されない情報'],
    ['送信される項目'],
    ['送信しない情報'],
  ])(
    'does NOT render the forbidden data-guarantee phrase "%s"',
    (phrase: string) => {
      const { container } = render(CrashDetectionModal, baseProps(makeCrash()));
      expect(container.textContent ?? '').not.toContain(phrase);
    },
  );

  it('renders both action buttons (cancel / preview)', () => {
    render(CrashDetectionModal, baseProps(makeCrash()));
    expect(screen.getByRole('button', { name: '今は送らない' })).toBeTruthy();
    expect(
      screen.getByRole('button', { name: /送信内容をプレビュー/ }),
    ).toBeTruthy();
  });

  it('preserves CJK + emoji + multi-line in exception_message', () => {
    render(
      CrashDetectionModal,
      baseProps(
        makeCrash({
          exception_message: '日本語エラー 🔥\n改行も含む',
        }),
      ),
    );
    const summary = screen.getByTestId('crash-summary');
    expect(summary.textContent).toContain('日本語エラー 🔥');
    expect(summary.textContent).toContain('改行も含む');
  });

  it('still renders when exception_message is empty (boundary)', () => {
    render(
      CrashDetectionModal,
      baseProps(makeCrash({ exception_message: '' })),
    );
    const summary = screen.getByTestId('crash-summary');
    // 型名だけは必ず出る
    expect(summary.textContent).toContain('RuntimeError');
  });

  it.each([
    ['fastapi'],
    ['excepthook'],
    ['signal'],
    ['atexit'],
    ['frontend'],
    ['unclean_shutdown'],
  ] as const)(
    'renders the same layout regardless of crash.source ("%s")',
    (source) => {
      render(
        CrashDetectionModal,
        baseProps(makeCrash({ source })),
      );
      // どの検知元でもボタン構成は同じ
      expect(screen.getByRole('button', { name: '今は送らない' })).toBeTruthy();
      expect(
        screen.getByRole('button', { name: /送信内容をプレビュー/ }),
      ).toBeTruthy();
    },
  );
});

describe('CrashDetectionModal — actions', () => {
  it('calls onDismiss when 「今は送らない」 is clicked', async () => {
    const onDismiss = vi.fn();
    render(CrashDetectionModal, baseProps(makeCrash(), { onDismiss }));
    await fireEvent.click(screen.getByRole('button', { name: '今は送らない' }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('calls onPreview with the crash object when プレビュー is clicked', async () => {
    const onPreview = vi.fn();
    const crash = makeCrash({ id: 'crash-xyz' });
    render(CrashDetectionModal, baseProps(crash, { onPreview }));
    await fireEvent.click(
      screen.getByRole('button', { name: /送信内容をプレビュー/ }),
    );
    expect(onPreview).toHaveBeenCalledTimes(1);
    expect(onPreview).toHaveBeenCalledWith(crash);
  });

  it('calls onDismiss when the Escape key is pressed', async () => {
    const onDismiss = vi.fn();
    render(CrashDetectionModal, baseProps(makeCrash(), { onDismiss }));
    await fireEvent.keyDown(window, { key: 'Escape' });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('does NOT close on backdrop click (明示クリック必須)', async () => {
    const onDismiss = vi.fn();
    const onPreview = vi.fn();
    const { container } = render(
      CrashDetectionModal,
      baseProps(makeCrash(), { onDismiss, onPreview }),
    );
    const backdrop = container.querySelector(
      '[data-testid="crash-modal-backdrop"]',
    ) as HTMLElement | null;
    expect(backdrop).not.toBeNull();
    await fireEvent.click(backdrop!);
    expect(onDismiss).not.toHaveBeenCalled();
    expect(onPreview).not.toHaveBeenCalled();
  });

  it('does NOT close on dialog content click (event does not bubble to dismiss)', async () => {
    const onDismiss = vi.fn();
    const { container } = render(
      CrashDetectionModal,
      baseProps(makeCrash(), { onDismiss }),
    );
    const dialog = container.querySelector('[role="alertdialog"]') as HTMLElement;
    await fireEvent.click(dialog);
    expect(onDismiss).not.toHaveBeenCalled();
  });
});

describe('crashReportsStore — activeImmediate slot (Task 5.6)', () => {
  function makeApi() {
    return {
      listPending: vi.fn().mockResolvedValue([]),
      dismiss: vi.fn().mockResolvedValue(undefined),
      markReported: vi.fn().mockResolvedValue(undefined),
    } as never;
  }

  it('activeImmediate starts as null', () => {
    const store = createCrashReportsStore(makeApi());
    expect(store.activeImmediate).toBeNull();
  });

  it('showImmediate(crash) makes activeImmediate point to that crash', () => {
    const store = createCrashReportsStore(makeApi());
    const crash = makeCrash({ id: 'one' });
    store.showImmediate(crash);
    expect(store.activeImmediate).not.toBeNull();
    expect(store.activeImmediate?.id).toBe('one');
  });

  it('clearImmediate resets activeImmediate to null', () => {
    const store = createCrashReportsStore(makeApi());
    store.showImmediate(makeCrash());
    store.clearImmediate();
    expect(store.activeImmediate).toBeNull();
  });

  it('clearImmediate is safe to call when no crash is active (idempotent)', () => {
    const store = createCrashReportsStore(makeApi());
    store.clearImmediate();
    store.clearImmediate();
    expect(store.activeImmediate).toBeNull();
  });

  it('showImmediate replaces a previously shown crash (latest wins)', () => {
    const store = createCrashReportsStore(makeApi());
    store.showImmediate(makeCrash({ id: 'first' }));
    store.showImmediate(makeCrash({ id: 'second' }));
    expect(store.activeImmediate?.id).toBe('second');
  });

  it('two independent stores do not share activeImmediate (no global state leak)', () => {
    const a = createCrashReportsStore(makeApi());
    const b = createCrashReportsStore(makeApi());
    a.showImmediate(makeCrash({ id: 'a' }));
    expect(a.activeImmediate?.id).toBe('a');
    expect(b.activeImmediate).toBeNull();
  });
});

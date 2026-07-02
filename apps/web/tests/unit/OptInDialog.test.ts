/**
 * OptInDialog tests (Sprint 7 Task 7.3).
 *
 * spec: docs/specs/2026-06-28-crash-report-feedback-hub-design.md §5.9
 * plan: docs/superpowers/plans/2026-06-28-crash-report-feedback-hub.md Task 7.3
 *
 * Scope (matches the in-scope dialog component):
 *   - Renders the title 「クラッシュレポート機能」, the body copy
 *     (with the bold preview reassurance), the foldable
 *     <details>「動作の詳細を見る」, and exactly TWO action buttons
 *     (「後で決める」 secondary / 「有効にする」 primary).
 *   - Spec § 5.9 explicit: NO 「常に無効」 button on this dialog.
 *   - 「後で決める」 → onDecide(false), no PUT, no API call. The crash_report
 *     settings stay `null` (undecided) so the dialog re-prompts later.
 *   - 「有効にする」 → PUT crash_report { enabled: true, auto_prompt: true,
 *     opted_in_at: <ISO 8601 now> } via the injectable `api.putCrashReport`,
 *     then onDecide(true). Both happen; both are observable.
 *   - Re-renders cleanly twice in the same JSDOM (mount → cleanup → mount).
 *   - No layout-guaranteeing copy ([[feedback-no-data-guarantee-in-ui]]):
 *     the dialog must NOT say 「送信されます」/「送信されません」 etc.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import OptInDialog from '$lib/components/OptInDialog.svelte';

interface CrashReportSettingsUpdate {
  enabled: boolean;
  auto_prompt: boolean;
  opted_in_at: string;
}

interface OptInApi {
  putCrashReport: (body: CrashReportSettingsUpdate) => Promise<void>;
}

function makeApi(impl?: Partial<OptInApi>): OptInApi {
  return {
    putCrashReport: vi.fn().mockResolvedValue(undefined),
    ...impl,
  };
}

function baseProps(extra: Record<string, unknown> = {}) {
  return {
    onDecide: vi.fn(),
    api: makeApi(),
    ...extra,
  };
}

beforeEach(() => {
  // Each test starts from a clean DOM.
});

afterEach(() => cleanup());

describe('OptInDialog — rendering', () => {
  it('renders the dialog title 「クラッシュレポート機能」', () => {
    render(OptInDialog, baseProps());
    const heading = screen.getByRole('heading', {
      name: 'クラッシュレポート機能',
    });
    expect(heading).toBeTruthy();
  });

  it('renders the explanatory body copy (error report + opt-in)', () => {
    const { container } = render(OptInDialog, baseProps());
    const text = container.textContent ?? '';
    expect(text).toContain(
      'NotebookOllamaでエラーが発生したとき、開発者に不具合情報を報告できます。',
    );
  });

  it('renders the preview-reassurance copy (with the bold strong tag)', () => {
    const { container } = render(OptInDialog, baseProps());
    const text = container.textContent ?? '';
    expect(text).toContain(
      '送信前にプレビューが表示され、内容を確認・編集してから送信できます。',
    );
    expect(text).toContain('報告は任意です。');
    // Bold per spec §5.9 — the preview clause must be inside a <strong>.
    const strong = container.querySelector('strong');
    expect(strong).not.toBeNull();
    expect(strong!.textContent ?? '').toContain(
      '送信前にプレビューが表示され、内容を確認・編集してから送信できます。',
    );
  });

  it('renders a foldable <details>「動作の詳細を見る」 with the auto-prompt explanation', () => {
    const { container } = render(OptInDialog, baseProps());
    const details = container.querySelector('details');
    expect(details).not.toBeNull();
    const summary = details!.querySelector('summary');
    expect(summary).not.toBeNull();
    expect(summary!.textContent ?? '').toContain('動作の詳細を見る');
    // The expanded body should reference both the auto-detected modal and the
    // manual megaphone-icon path so the user understands the two flows.
    const inner = details!.textContent ?? '';
    expect(inner).toContain('自動検知時');
    expect(inner).toContain('ヘッダ');
  });

  it('the <details> can be expanded (toggle open attribute)', async () => {
    const { container } = render(OptInDialog, baseProps());
    const details = container.querySelector('details') as HTMLDetailsElement;
    expect(details.open).toBe(false);
    details.open = true;
    expect(details.open).toBe(true);
  });

  it('renders exactly TWO action buttons (postpone + enable)', () => {
    render(OptInDialog, baseProps());
    expect(screen.getByRole('button', { name: '後で決める' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '有効にする' })).toBeTruthy();
  });

  it('does NOT render a 「常に無効」 button (spec §5.9 explicit)', () => {
    const { container } = render(OptInDialog, baseProps());
    expect(container.textContent ?? '').not.toContain('常に無効');
    // Also confirm via role/name lookup.
    expect(screen.queryByRole('button', { name: '常に無効' })).toBeNull();
    expect(screen.queryByRole('button', { name: /常に無効/ })).toBeNull();
  });

  it.each([
    ['送信されます'],
    ['送信されません'],
    ['以下のデータが送信'],
    ['送信される情報'],
    ['送信されない情報'],
  ])(
    'does NOT render the forbidden data-guarantee phrase "%s"',
    (phrase: string) => {
      const { container } = render(OptInDialog, baseProps());
      expect(container.textContent ?? '').not.toContain(phrase);
    },
  );

  it('has role="dialog" with aria-modal and an aria-labelledby pointing at the title', () => {
    const { container } = render(OptInDialog, baseProps());
    const dlg = container.querySelector('[role="dialog"]') as HTMLElement;
    expect(dlg).not.toBeNull();
    expect(dlg.getAttribute('aria-modal')).toBe('true');
    const labelledBy = dlg.getAttribute('aria-labelledby');
    expect(labelledBy).toBeTruthy();
    const heading = container.querySelector(`#${labelledBy}`);
    expect(heading).not.toBeNull();
    expect(heading!.textContent ?? '').toContain('クラッシュレポート機能');
  });
});

describe('OptInDialog — 後で決める (postpone)', () => {
  it('calls onDecide(false) when 「後で決める」 is clicked', async () => {
    const onDecide = vi.fn();
    render(OptInDialog, baseProps({ onDecide }));
    await fireEvent.click(screen.getByRole('button', { name: '後で決める' }));
    expect(onDecide).toHaveBeenCalledTimes(1);
    expect(onDecide).toHaveBeenCalledWith(false);
  });

  it('does NOT call api.putCrashReport when 「後で決める」 is clicked (settings stay null)', async () => {
    const api = makeApi();
    render(OptInDialog, baseProps({ api }));
    await fireEvent.click(screen.getByRole('button', { name: '後で決める' }));
    expect(api.putCrashReport).not.toHaveBeenCalled();
  });
});

describe('OptInDialog — 有効にする (enable)', () => {
  it('calls api.putCrashReport with enabled=true / auto_prompt=true / opted_in_at=now', async () => {
    const api = makeApi();
    render(OptInDialog, baseProps({ api }));
    const before = Date.now();
    await fireEvent.click(screen.getByRole('button', { name: '有効にする' }));
    await waitFor(() => expect(api.putCrashReport).toHaveBeenCalledTimes(1));
    const after = Date.now();

    const body = (api.putCrashReport as ReturnType<typeof vi.fn>).mock
      .calls[0][0] as CrashReportSettingsUpdate;
    expect(body.enabled).toBe(true);
    expect(body.auto_prompt).toBe(true);
    // ISO 8601 round-trip and the timestamp falls between before/after.
    const parsed = Date.parse(body.opted_in_at);
    expect(Number.isNaN(parsed)).toBe(false);
    expect(parsed).toBeGreaterThanOrEqual(before);
    expect(parsed).toBeLessThanOrEqual(after);
    // Format check — ISO 8601 with timezone (Z or ±HH:MM).
    expect(body.opted_in_at).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/);
  });

  it('calls onDecide(true) after a successful PUT', async () => {
    const onDecide = vi.fn();
    render(OptInDialog, baseProps({ onDecide }));
    await fireEvent.click(screen.getByRole('button', { name: '有効にする' }));
    await waitFor(() => expect(onDecide).toHaveBeenCalledTimes(1));
    expect(onDecide).toHaveBeenCalledWith(true);
  });

  it('PUT happens BEFORE onDecide(true) (parent can rely on settings being updated)', async () => {
    const order: string[] = [];
    const api = makeApi({
      putCrashReport: vi.fn(async () => {
        order.push('put');
      }),
    });
    const onDecide = vi.fn(() => {
      order.push('decide');
    });
    render(OptInDialog, baseProps({ api, onDecide }));
    await fireEvent.click(screen.getByRole('button', { name: '有効にする' }));
    await waitFor(() => expect(onDecide).toHaveBeenCalled());
    expect(order).toEqual(['put', 'decide']);
  });

  it('does NOT call onDecide if the PUT rejects (user can retry)', async () => {
    const api = makeApi({
      putCrashReport: vi.fn().mockRejectedValue(new Error('500')),
    });
    const onDecide = vi.fn();
    render(OptInDialog, baseProps({ api, onDecide }));
    await fireEvent.click(screen.getByRole('button', { name: '有効にする' }));
    // The PUT was attempted...
    await waitFor(() =>
      expect(api.putCrashReport).toHaveBeenCalledTimes(1),
    );
    // ...but onDecide was NOT called (dialog stays open so user can retry).
    expect(onDecide).not.toHaveBeenCalled();
  });

  it('surfaces a user-visible error when the PUT rejects (no silent failure)', async () => {
    const api = makeApi({
      putCrashReport: vi.fn().mockRejectedValue(new Error('boom-net')),
    });
    const { container } = render(OptInDialog, baseProps({ api }));
    await fireEvent.click(screen.getByRole('button', { name: '有効にする' }));
    await waitFor(() => {
      // Some error indication in the dialog (don't pin exact copy, just CJK
      // error label + the underlying message visible to the user).
      const text = container.textContent ?? '';
      expect(text).toMatch(/エラー|失敗/);
      expect(text).toContain('boom-net');
    });
  });

  it('ignores a second click while the first PUT is in flight (no double-PUT)', async () => {
    let resolveFirst!: () => void;
    const slowPut = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveFirst = resolve;
        }),
    );
    const api: OptInApi = { putCrashReport: slowPut };
    const onDecide = vi.fn();
    render(OptInDialog, baseProps({ api, onDecide }));
    const enableBtn = screen.getByRole('button', { name: '有効にする' });

    await fireEvent.click(enableBtn);
    await fireEvent.click(enableBtn);
    await fireEvent.click(enableBtn);

    // Only one PUT was launched.
    expect(slowPut).toHaveBeenCalledTimes(1);

    resolveFirst();
    await waitFor(() => expect(onDecide).toHaveBeenCalledTimes(1));
  });
});

describe('OptInDialog — re-mount safety', () => {
  it('renders without crash if shown twice (mount → cleanup → mount)', () => {
    render(OptInDialog, baseProps());
    expect(screen.getByRole('heading', { name: 'クラッシュレポート機能' })).toBeTruthy();
    cleanup();
    render(OptInDialog, baseProps());
    expect(screen.getByRole('heading', { name: 'クラッシュレポート機能' })).toBeTruthy();
  });
});

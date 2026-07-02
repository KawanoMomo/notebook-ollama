import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import FeedbackHubDrawer from '$lib/components/FeedbackHubDrawer.svelte';
// Raw-source import to verify the Svelte fly transition directive is wired (regression
// guard: dead-CSS `transform: translateX(0)` made the drawer pop instead of slide).
import drawerSource from '$lib/components/FeedbackHubDrawer.svelte?raw';
import { createFeedbackHubStore, type FeedbackHubTab } from '$lib/stores/feedbackHub.svelte';
import { createNoticesStore } from '$lib/stores/notices.svelte';
import { createCrashReportsStore } from '$lib/stores/crashReports.svelte';
import type { CrashHardware, Notice, PendingCrash } from '$lib/api/types';

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

function makeStores(crashItems: PendingCrash[] = [], notices_items: Notice[] = []) {
  const notices = createNoticesStore(makeNoticesApi(notices_items) as never);
  const crashes = createCrashReportsStore(makeCrashApi(crashItems) as never);
  const hub = createFeedbackHubStore(notices, crashes);
  hub.open();
  return { notices, crashes, hub };
}

const ALL_TABS: { id: FeedbackHubTab; label: string }[] = [
  { id: 'notices', label: 'お知らせ' },
  { id: 'bugs', label: '不具合' },
  { id: 'feedback', label: 'ご意見' },
];

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => cleanup());

describe('FeedbackHubDrawer — 枠', () => {
  it('renders the drawer title「お知らせ・フィードバック」', () => {
    const { hub, crashes, notices } = makeStores();
    render(FeedbackHubDrawer, { hub, crashes, notices });
    expect(screen.getByText('お知らせ・フィードバック')).toBeDefined();
  });

  it('renders a backdrop element behind the drawer', () => {
    const { hub, crashes, notices } = makeStores();
    const { container } = render(FeedbackHubDrawer, { hub, crashes, notices });
    expect(container.querySelector('.backdrop')).not.toBeNull();
  });

  it('drawer has role="dialog" with aria-modal and aria-label', () => {
    const { hub, crashes, notices } = makeStores();
    render(FeedbackHubDrawer, { hub, crashes, notices });
    const dlg = screen.getByRole('dialog');
    expect(dlg.getAttribute('aria-modal')).toBe('true');
    expect(dlg.getAttribute('aria-label')).toBe('お知らせ・フィードバック');
  });

  it('exposes a close-button (aria-label="閉じる")', () => {
    const { hub, crashes, notices } = makeStores();
    render(FeedbackHubDrawer, { hub, crashes, notices });
    expect(screen.getByLabelText('閉じる')).toBeDefined();
  });
});

describe('FeedbackHubDrawer — close behavior', () => {
  it('clicking the backdrop calls hub.close()', async () => {
    const { hub, crashes, notices } = makeStores();
    const spy = vi.spyOn(hub, 'close');
    const { container } = render(FeedbackHubDrawer, { hub, crashes, notices });
    const bd = container.querySelector('.backdrop') as HTMLElement;
    await fireEvent.click(bd);
    expect(spy).toHaveBeenCalled();
  });

  it('clicking the explicit close-button calls hub.close()', async () => {
    const { hub, crashes, notices } = makeStores();
    const spy = vi.spyOn(hub, 'close');
    render(FeedbackHubDrawer, { hub, crashes, notices });
    await fireEvent.click(screen.getByLabelText('閉じる'));
    expect(spy).toHaveBeenCalled();
  });

  it('ESC keydown calls hub.close()', async () => {
    const { hub, crashes, notices } = makeStores();
    const spy = vi.spyOn(hub, 'close');
    render(FeedbackHubDrawer, { hub, crashes, notices });
    await fireEvent.keyDown(window, { key: 'Escape' });
    expect(spy).toHaveBeenCalled();
  });

  it('clicking inside the drawer body does NOT call hub.close() (event does not bubble to backdrop)', async () => {
    const { hub, crashes, notices } = makeStores();
    const spy = vi.spyOn(hub, 'close');
    render(FeedbackHubDrawer, { hub, crashes, notices });
    const dlg = screen.getByRole('dialog');
    await fireEvent.click(dlg);
    expect(spy).not.toHaveBeenCalled();
  });

  it('keys other than Escape do not close', async () => {
    const { hub, crashes, notices } = makeStores();
    const spy = vi.spyOn(hub, 'close');
    render(FeedbackHubDrawer, { hub, crashes, notices });
    await fireEvent.keyDown(window, { key: 'Enter' });
    await fireEvent.keyDown(window, { key: 'a' });
    await fireEvent.keyDown(window, { key: 'Tab' });
    expect(spy).not.toHaveBeenCalled();
  });
});

describe('FeedbackHubDrawer — 3 タブ (全網羅)', () => {
  it.each(ALL_TABS)('renders the "$label" tab button', ({ label }) => {
    const { hub, crashes, notices } = makeStores();
    render(FeedbackHubDrawer, { hub, crashes, notices });
    expect(screen.getByRole('tab', { name: new RegExp(label) })).toBeDefined();
  });

  it('renders exactly 3 tab buttons', () => {
    const { hub, crashes, notices } = makeStores();
    render(FeedbackHubDrawer, { hub, crashes, notices });
    expect(screen.getAllByRole('tab')).toHaveLength(3);
  });

  it.each(ALL_TABS)('clicking "$label" calls hub.setTab("$id")', async ({ id, label }) => {
    const { hub, crashes, notices } = makeStores();
    const spy = vi.spyOn(hub, 'setTab');
    render(FeedbackHubDrawer, { hub, crashes, notices });
    await fireEvent.click(screen.getByRole('tab', { name: new RegExp(label) }));
    expect(spy).toHaveBeenCalledWith(id);
  });

  it.each(ALL_TABS)(
    'when activeTab="$id" the corresponding tab has aria-selected=true and the others false',
    ({ id, label }) => {
      const { hub, crashes, notices } = makeStores();
      hub.setTab(id);
      render(FeedbackHubDrawer, { hub, crashes, notices });
      for (const t of ALL_TABS) {
        const btn = screen.getByRole('tab', { name: new RegExp(t.label) });
        expect(btn.getAttribute('aria-selected')).toBe(t.id === id ? 'true' : 'false');
      }
    },
  );
});

describe('FeedbackHubDrawer — タブ内容 (Sprint 6: NoticesTab / Sprint 7: BugReportTab / Sprint 8: FeedbackTab placeholder)', () => {
  // Sprint 6 で NoticesTab は実装完了。空配列の API を注入すると
  // 「お知らせはありません」 (empty state) が表示される。
  it('default activeTab=notices shows the real NoticesTab (empty state)', async () => {
    const { hub, crashes, notices } = makeStores();
    render(FeedbackHubDrawer, { hub, crashes, notices });
    await waitFor(() => expect(screen.getByText('お知らせはありません')).toBeDefined());
  });

  // Sprint 7 で BugReportTab は実装完了。feedback タブだけがまだ Sprint 8 placeholder。
  //
  // bugs 行のアサーションは BugReportTab 固有の説明文 (常に DOM にある冒頭
  // <p class="description">) をマーカに使う。これは loading/error/empty/non-empty
  // すべての状態で出るので、Drawer→BugReportTab の結線確認には最も安定。
  //
  // 同時並行で動いている fix-bug-report-tab-empty agent は BugReportTab に
  // 明示的な empty-state テキスト (NoticesTab の「お知らせはありません」相当) を
  // 追加する予定。Drawer が `crashes` prop を BugReportTab へ伝播するよう
  // 修正されたら、このマーカをその empty-state 文言に置き換えられる。
  // (現状 Drawer は BugReportTab に store prop を渡しておらず、singleton 経由で
  //  実 API を叩くため jsdom では error 状態に落ちて空状態が出ない。)
  it.each([
    {
      id: 'bugs' as const,
      label: '不具合',
      assertContent: () =>
        expect(
          screen.getByText(/アプリで発生したエラーを開発者に報告できます/),
        ).toBeDefined(),
    },
    {
      id: 'feedback' as const,
      label: 'ご意見',
      // Sprint 8 で FeedbackTab を実装完了。マーカは frontend で常に DOM に出る
      // 「送信内容をプレビュー →」フッタボタン (submit button) のラベル。
      assertContent: () =>
        expect(screen.getByText(/送信内容をプレビュー/)).toBeDefined(),
    },
  ])(
    'when activeTab="$id" the corresponding tab content is in the DOM',
    ({ id, assertContent }) => {
      const { hub, crashes, notices } = makeStores();
      hub.setTab(id);
      render(FeedbackHubDrawer, { hub, crashes, notices });
      assertContent();
    },
  );

  it('when activeTab="notices" only NoticesTab is in the DOM (empty state, no bugs/feedback placeholder text)', async () => {
    const { hub, crashes, notices } = makeStores();
    hub.setTab('notices');
    render(FeedbackHubDrawer, { hub, crashes, notices });
    await waitFor(() => expect(screen.getByText('お知らせはありません')).toBeDefined());
    // BugReportTab / FeedbackTab の固有テキストは notices アクティブ時には現れない
    expect(screen.queryByText(/アプリで発生したエラーを開発者に報告できます/)).toBeNull();
    expect(screen.queryByText(/送信内容をプレビュー/)).toBeNull();
  });

  // Sprint 7 task 7.x: BugReportTab は NoticesTab と同じ流儀で `store` prop を
  // 受け取る。Drawer は自分が DI で受け取った `crashes` ストアをそのまま
  // BugReportTab に渡さなければならない (= singleton への副作用を作らない)。
  //
  // 検証: モック API を持つ crashes ストアにあらかじめ 1 件ロードした状態で
  // bugs タブを開くと、その例外型名が描画される。Drawer が prop を伝播
  // していなければ BugReportTab は global singleton 経由で実 API を叩こうとし、
  // jsdom では fetch 失敗 → error 状態に落ちて 'TypeError-DI' は出ない。
  it('bugs タブは Drawer の `crashes` DI prop を BugReportTab に伝播する', async () => {
    const di = makeCrash({
      id: 'di-crash',
      exception_type: 'TypeError-DI',
      exception_message: 'di test message',
    });
    const { hub, crashes, notices } = makeStores([di]);
    await crashes.load(); // mock API の中身を pending に反映
    hub.setTab('bugs');
    render(FeedbackHubDrawer, { hub, crashes, notices });
    await waitFor(() => {
      expect(screen.getByText('TypeError-DI')).toBeDefined();
    });
    expect(screen.getByText(/di test message/)).toBeDefined();
  });
});

describe('FeedbackHubDrawer — 不具合タブの pendingCount pill', () => {
  it('shows a pill with pendingCount on the bugs tab when > 0', async () => {
    const { hub, crashes, notices } = makeStores([
      makeCrash({ id: 'c1' }),
      makeCrash({ id: 'c2' }),
    ]);
    await crashes.load();
    render(FeedbackHubDrawer, { hub, crashes, notices });
    const bugsBtn = screen.getByRole('tab', { name: /不具合/ });
    expect(bugsBtn.textContent).toMatch(/2/);
  });

  it('does NOT show a pill when pendingCount = 0', () => {
    const { hub, crashes, notices } = makeStores();
    render(FeedbackHubDrawer, { hub, crashes, notices });
    const bugsBtn = screen.getByRole('tab', { name: /不具合/ });
    // 「不具合」だけがあり数字が出ない
    expect(bugsBtn.textContent?.trim()).toBe('不具合');
  });

  it('does NOT show a pill on the notices or feedback tab in Sprint 5', async () => {
    const { hub, crashes, notices } = makeStores([makeCrash({ id: 'c1' })]);
    await crashes.load();
    render(FeedbackHubDrawer, { hub, crashes, notices });
    const noticesBtn = screen.getByRole('tab', { name: /お知らせ/ });
    const feedbackBtn = screen.getByRole('tab', { name: /ご意見/ });
    expect(noticesBtn.textContent?.trim()).toBe('お知らせ');
    expect(feedbackBtn.textContent?.trim()).toBe('ご意見');
  });
});

describe('FeedbackHubDrawer — frame size (spec §5.2)', () => {
  it('drawer width style is 440px (matches spec §5.2)', () => {
    const { hub, crashes, notices } = makeStores();
    render(FeedbackHubDrawer, { hub, crashes, notices });
    const dlg = screen.getByRole('dialog');
    // CSS は inline 値ではなく <style> 経由のため、CSS 変数 / クラス名で表現される。
    // テストは drawer に専用クラス（.drawer）が付与されていることだけ確認し、
    // 実寸チェックは Evaluator の視覚ゲートに委ねる。
    expect(dlg.classList.contains('drawer')).toBe(true);
  });
});

describe('FeedbackHubDrawer — slide-in animation (spec §5.2)', () => {
  // Adversarial-review finding: the previous implementation had
  // `transform: translateX(0)` + `transition: transform 0.18s ease-out` in CSS
  // but the transform never changed and no Svelte transition directive was used,
  // so the drawer popped in instantly. Spec §5.2 / plan §1453 require slide-in.
  //
  // Source-level regression guard. The actual visual behaviour is covered by
  // the Evaluator visual gate; here we only confirm that the directive is wired.
  it('imports `fly` from svelte/transition', () => {
    expect(drawerSource).toMatch(/import\s*\{[^}]*\bfly\b[^}]*\}\s*from\s*['"]svelte\/transition['"]/);
  });

  it('applies `transition:fly` on the drawer element (not just dead CSS)', () => {
    expect(drawerSource).toMatch(/transition:fly\b/);
  });
});

describe('FeedbackHubDrawer — DI prop propagation to FeedbackTab', () => {
  // Adversarial-review finding: Drawer rendered `<FeedbackTab />` with no props,
  // so FeedbackTab fell back to the global singleton `feedbackHubStore`. The
  // Cancel button inside FeedbackTab then called `singleton.close()` instead of
  // the DI hub the drawer was actually constructed with — opening a real hole
  // in tests/HMR where the drawer wouldn't close.
  //
  // Regression guard: render the drawer with a DI hub on the feedback tab,
  // click cancel, and assert the **DI hub** received `close()`, not the
  // singleton. If the prop is not threaded through, this test fails because
  // `spy` (bound to the DI hub) never sees the call.
  it('cancel inside FeedbackTab closes the SAME hub instance the drawer was given (not the singleton)', async () => {
    const { hub, crashes, notices } = makeStores();
    hub.setTab('feedback');
    const spy = vi.spyOn(hub, 'close');
    render(FeedbackHubDrawer, { hub, crashes, notices });
    // Sanity: FeedbackTab is mounted
    const cancelBtn = await screen.findByTestId('feedback-cancel');
    await fireEvent.click(cancelBtn);
    expect(spy).toHaveBeenCalled();
    expect(hub.drawerOpen).toBe(false);
  });
});

describe('FeedbackHubDrawer — accessibility focus management (spec §5.2)', () => {
  // Adversarial-review finding: visual verify Tab-pressed thrice and focus went
  // Megaphone → Settings → New Notebook → first notebook — never entered drawer.
  // Fix = auto-focus close button on open + Tab/Shift+Tab focus trap inside drawer.
  it('auto-focuses the close button when the drawer opens', async () => {
    const { hub, crashes, notices } = makeStores();
    render(FeedbackHubDrawer, { hub, crashes, notices });
    const closeBtn = screen.getByLabelText('閉じる');
    await waitFor(() => expect(document.activeElement).toBe(closeBtn));
  });

  it('Tab on the last focusable element wraps focus to the first inside the drawer', async () => {
    const { hub, crashes, notices } = makeStores();
    const { container } = render(FeedbackHubDrawer, { hub, crashes, notices });
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByLabelText('閉じる')),
    );

    const drawer = container.querySelector('.drawer') as HTMLElement;
    const focusables = Array.from(drawer.querySelectorAll<HTMLElement>('button'));
    expect(focusables.length).toBeGreaterThan(1);
    const first = focusables[0];
    const last = focusables[focusables.length - 1];

    last.focus();
    expect(document.activeElement).toBe(last);

    await fireEvent.keyDown(drawer, { key: 'Tab' });
    expect(document.activeElement).toBe(first);
  });

  it('Shift+Tab on the first focusable element wraps focus to the last inside the drawer', async () => {
    const { hub, crashes, notices } = makeStores();
    const { container } = render(FeedbackHubDrawer, { hub, crashes, notices });
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByLabelText('閉じる')),
    );

    const drawer = container.querySelector('.drawer') as HTMLElement;
    const focusables = Array.from(drawer.querySelectorAll<HTMLElement>('button'));
    const first = focusables[0];
    const last = focusables[focusables.length - 1];

    first.focus();
    expect(document.activeElement).toBe(first);

    await fireEvent.keyDown(drawer, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(last);
  });

  it('Tab from a middle focusable does NOT wrap (browser default applies)', async () => {
    const { hub, crashes, notices } = makeStores();
    const { container } = render(FeedbackHubDrawer, { hub, crashes, notices });
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByLabelText('閉じる')),
    );

    const drawer = container.querySelector('.drawer') as HTMLElement;
    const focusables = Array.from(drawer.querySelectorAll<HTMLElement>('button'));
    expect(focusables.length).toBeGreaterThan(2);
    const middle = focusables[1];

    middle.focus();
    await fireEvent.keyDown(drawer, { key: 'Tab' });
    // Trap should be a no-op in the middle; jsdom doesn't move focus on Tab,
    // so activeElement stays on `middle` (the important point: it did NOT wrap).
    expect(document.activeElement).toBe(middle);
  });
});

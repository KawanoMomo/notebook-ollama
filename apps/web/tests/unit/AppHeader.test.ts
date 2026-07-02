/**
 * AppHeader: Megaphone (feedback hub) ボタン + 未読ドットの単体テスト。
 *
 * spec: docs/specs/2026-06-28-crash-report-feedback-hub-design.md §5.1
 * plan: Task 5.4
 *
 * 検証項目:
 *   - Megaphone ボタンが存在する (aria-label "お知らせ・フィードバック")
 *   - Settings ボタン (aria-label "設定") の **直前** (左隣) に置かれている
 *   - クリック時に `feedbackHubStore.open()` が呼ばれる
 *   - `unreadCount === 0` のときは未読ドットを描画しない
 *   - `unreadCount > 0` のときは右上に未読ドット (aria-label "未読あり") を描画する
 *
 * 実装は singleton `feedbackHubStore` を直接参照するため (plan §5.4 の Interfaces
 * を忠実に再現)、テスト側は `vi.mock` で singleton を差し替える。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/svelte';

// vi.hoisted で巻き上げ。vi.mock factory より先に評価されることを保証する。
const mockHub = vi.hoisted(() => ({
  feedbackHubStore: {
    drawerOpen: false,
    activeTab: 'notices' as const,
    unreadCount: 0,
    open: vi.fn(),
    close: vi.fn(),
    setTab: vi.fn(),
  },
}));

vi.mock('$lib/stores/feedbackHub.svelte', () => mockHub);

import AppHeader from '$lib/components/AppHeader.svelte';

beforeEach(() => {
  // 各テストで singleton の状態をリセット
  mockHub.feedbackHubStore.drawerOpen = false;
  mockHub.feedbackHubStore.activeTab = 'notices';
  mockHub.feedbackHubStore.unreadCount = 0;
  mockHub.feedbackHubStore.open.mockReset();
  mockHub.feedbackHubStore.close.mockReset();
  mockHub.feedbackHubStore.setTab.mockReset();
});

afterEach(() => cleanup());

describe('AppHeader — Megaphone ボタン', () => {
  it('Megaphone ボタンが描画される (aria-label "お知らせ・フィードバック")', () => {
    const { container } = render(AppHeader);
    const btn = container.querySelector('button[aria-label="お知らせ・フィードバック"]');
    expect(btn).not.toBeNull();
  });

  it('Megaphone ボタンは Settings リンクの直前 (左隣) に配置される', () => {
    const { container } = render(AppHeader);
    const actions = container.querySelector('.actions');
    expect(actions).not.toBeNull();

    const interactiveChildren = Array.from(actions!.children).filter(
      (el) =>
        el.getAttribute('aria-label') === 'お知らせ・フィードバック' ||
        el.getAttribute('aria-label') === '設定',
    );
    // Megaphone (button) が先、Settings (a) が後
    expect(interactiveChildren).toHaveLength(2);
    expect(interactiveChildren[0].getAttribute('aria-label')).toBe('お知らせ・フィードバック');
    expect(interactiveChildren[1].getAttribute('aria-label')).toBe('設定');
  });

  it('Megaphone ボタンクリックで feedbackHubStore.open() が呼ばれる', async () => {
    const { container } = render(AppHeader);
    const btn = container.querySelector(
      'button[aria-label="お知らせ・フィードバック"]',
    ) as HTMLButtonElement;
    expect(btn).not.toBeNull();

    await fireEvent.click(btn);
    expect(mockHub.feedbackHubStore.open).toHaveBeenCalledTimes(1);
  });
});

describe('AppHeader — 未読ドット', () => {
  it('unreadCount === 0 のとき未読ドットを描画しない', () => {
    mockHub.feedbackHubStore.unreadCount = 0;
    const { container } = render(AppHeader);
    expect(container.querySelector('[aria-label="未読あり"]')).toBeNull();
  });

  it('unreadCount > 0 のとき未読ドット (aria-label "未読あり") を描画する', () => {
    mockHub.feedbackHubStore.unreadCount = 1;
    const { container } = render(AppHeader);
    const dot = container.querySelector('[aria-label="未読あり"]');
    expect(dot).not.toBeNull();
  });

  // boundary: 大きな未読数 / 境界値も網羅
  it.each([1, 2, 99, 9999])(
    'unreadCount=%i のとき未読ドットが描画される',
    (n) => {
      mockHub.feedbackHubStore.unreadCount = n;
      const { container } = render(AppHeader);
      expect(container.querySelector('[aria-label="未読あり"]')).not.toBeNull();
    },
  );

  it('未読ドットは Megaphone ボタンの内部 (子孫) に置かれる', () => {
    mockHub.feedbackHubStore.unreadCount = 3;
    const { container } = render(AppHeader);
    const btn = container.querySelector(
      'button[aria-label="お知らせ・フィードバック"]',
    );
    expect(btn).not.toBeNull();
    const dot = btn!.querySelector('[aria-label="未読あり"]');
    expect(dot).not.toBeNull();
  });
});

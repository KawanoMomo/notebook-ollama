/**
 * BetaFeaturesSection — 設定画面「ベータ機能」セクション (Task 4)
 *
 * spec: docs/specs/2026-07-20-beta-feature-flags-design.md
 *
 * テスト方針: CrashReportSection.test.ts と同様、DI (`features` prop) で
 * テストごとに独立インスタンスを渡す。「結線が正しい」ことを中心に検証する。
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';

import BetaFeaturesSection from '$lib/components/settings/BetaFeaturesSection.svelte';
import { createFeaturesStore, type FeaturesStore } from '$lib/stores/features.svelte';
import type { FeatureFlagInfo } from '$lib/api/types';

function makeFlag(overrides: Partial<FeatureFlagInfo> = {}): FeatureFlagInfo {
  return {
    id: 'table-figure-rag',
    name: '表・図検索強化',
    description: 'PDFの表・図を抽出し、検索と回答に反映するベータ機能',
    stage: 'beta',
    enabled: false,
    ...overrides,
  };
}

function makeApi(features: FeatureFlagInfo[] = []) {
  return {
    list: vi.fn().mockResolvedValue({ features }),
    setOptin: vi.fn().mockResolvedValue({ features }),
  };
}

async function setup(flags: FeatureFlagInfo[] = [makeFlag()]) {
  const api = makeApi(flags);
  const features: FeaturesStore = createFeaturesStore(api as never);
  await features.load();
  return { features, api };
}

afterEach(() => cleanup());

describe('BetaFeaturesSection — 描画', () => {
  it('見出し「ベータ機能」と説明文を描画する', async () => {
    const { features } = await setup();
    render(BetaFeaturesSection, { features });
    expect(screen.getByRole('heading', { name: /ベータ機能/ })).toBeDefined();
    expect(screen.getByText(/評価中の機能です/)).toBeDefined();
  });

  it('betaFlags の各フラグを name/description 付きで描画する', async () => {
    const flags = [
      makeFlag({ id: 'a', name: 'フラグA', description: '説明A' }),
      makeFlag({ id: 'b', name: 'フラグB', description: '説明B' }),
    ];
    const { features } = await setup(flags);
    render(BetaFeaturesSection, { features });
    expect(screen.getByText('フラグA', { exact: true })).toBeDefined();
    expect(screen.getByText('説明A')).toBeDefined();
    expect(screen.getByText('フラグB', { exact: true })).toBeDefined();
    expect(screen.getByText('説明B')).toBeDefined();
  });

  it('betaFlags が空のときは何も描画しない', async () => {
    const { features } = await setup([]);
    render(BetaFeaturesSection, { features });
    expect(screen.queryByRole('heading', { name: /ベータ機能/ })).toBeNull();
    expect(screen.queryByRole('switch')).toBeNull();
  });

  it('stage=ga のフラグは一覧に含まれない (store 側で除外済み)', async () => {
    const flags = [
      makeFlag({ id: 'beta-1', name: 'ベータ機能A' }),
      makeFlag({ id: 'ga-1', name: 'GA機能A', stage: 'ga', enabled: true }),
    ];
    const { features } = await setup(flags);
    render(BetaFeaturesSection, { features });
    expect(screen.getByText('ベータ機能A', { exact: true })).toBeDefined();
    expect(screen.queryByText('GA機能A', { exact: true })).toBeNull();
  });
});

describe('BetaFeaturesSection — toggle', () => {
  it('enabled=false のとき switch は OFF (aria-checked=false)', async () => {
    const { features } = await setup([makeFlag({ enabled: false })]);
    render(BetaFeaturesSection, { features });
    const sw = screen.getByRole('switch', { name: /表・図検索強化/ });
    expect(sw.getAttribute('aria-checked')).toBe('false');
  });

  it('enabled=true のとき switch は ON (aria-checked=true)', async () => {
    const { features } = await setup([makeFlag({ enabled: true })]);
    render(BetaFeaturesSection, { features });
    const sw = screen.getByRole('switch', { name: /表・図検索強化/ });
    expect(sw.getAttribute('aria-checked')).toBe('true');
  });

  it('クリックで features.setOptin(id, true) が呼ばれ ON に切り替わる', async () => {
    const { features, api } = await setup([makeFlag({ id: 'a', enabled: false })]);
    api.setOptin.mockResolvedValueOnce({
      features: [makeFlag({ id: 'a', enabled: true })],
    });
    render(BetaFeaturesSection, { features });
    const sw = screen.getByRole('switch', { name: /表・図検索強化/ });
    await fireEvent.click(sw);
    await waitFor(() => expect(api.setOptin).toHaveBeenCalledWith('a', true));
    await waitFor(() => expect(sw.getAttribute('aria-checked')).toBe('true'));
  });

  it('クリックで true → false へ切り替わる', async () => {
    const { features, api } = await setup([makeFlag({ id: 'a', enabled: true })]);
    api.setOptin.mockResolvedValueOnce({
      features: [makeFlag({ id: 'a', enabled: false })],
    });
    render(BetaFeaturesSection, { features });
    const sw = screen.getByRole('switch', { name: /表・図検索強化/ });
    await fireEvent.click(sw);
    await waitFor(() => expect(api.setOptin).toHaveBeenCalledWith('a', false));
  });
});

describe('BetaFeaturesSection — 使い方ガイド(実機FB 2026-07-26)', () => {
  it('table-figure-rag の行に展開式の使い方ガイドが付く', async () => {
    const { features } = await setup();
    render(BetaFeaturesSection, { features });
    const summary = screen.getByText('使い方を見る（スクリーンショット付き）');
    expect(summary).toBeDefined();
    // 展開するとステップ見出しとスクリーンショット4枚が現れる
    await fireEvent.click(summary);
    expect(screen.getByText(/Step 1\./)).toBeDefined();
    expect(screen.getByText(/Step 4\./)).toBeDefined();
    const imgs = document.querySelectorAll('.guide-body img');
    expect(imgs.length).toBe(4);
    expect((imgs[0] as HTMLImageElement).getAttribute('src')).toContain('/help/table-figure-rag/');
    // 全imgにaltがある(アクセシビリティ)
    for (const img of imgs) expect((img.getAttribute('alt') ?? '').length).toBeGreaterThan(0);
  });

  it('他のフラグにはガイドが付かない', async () => {
    const { features } = await setup([
      makeFlag({ id: 'some-other-flag', name: '別機能' }),
    ]);
    render(BetaFeaturesSection, { features });
    expect(screen.queryByText('使い方を見る（スクリーンショット付き）')).toBeNull();
  });
});

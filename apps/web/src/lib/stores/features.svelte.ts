/**
 * features store — ベータ機能フラグ一覧。
 *
 * spec: docs/specs/2026-07-20-beta-feature-flags-design.md
 * api : apps/web/src/lib/api/features.ts (featuresApi.list / setOptin)
 *
 * `flags` は backend `core/feature_service.py::FeatureService.list_flags()` の
 * 全件をそのまま保持する。`betaFlags` は `stage === 'beta'` のみの derived で、
 * 設定画面の「ベータ機能」ナビ項目・セクションが空件数のとき描画を止める判定に使う。
 *
 * `setOptin` は API 呼び出し成功後にレスポンスの最新一覧で `flags` を丸ごと
 * 置き換える(crashReportsStore の楽観削除とは異なり、サーバ側が確定させた
 * 状態をそのまま反映する方が確実なため)。失敗時は例外が呼び出し元へ伝播し、
 * `flags` は変更されない。
 */
import { featuresApi } from '$lib/api/features';
import type { FeatureFlagInfo } from '$lib/api/types';

type FeaturesApi = Pick<typeof featuresApi, 'list' | 'setOptin'>;

export interface FeaturesStore {
  readonly flags: FeatureFlagInfo[];
  readonly betaFlags: FeatureFlagInfo[];
  readonly loading: boolean;
  readonly error: string | null;
  load(): Promise<void>;
  setOptin(id: string, enabled: boolean): Promise<void>;
}

export function createFeaturesStore(api: FeaturesApi = featuresApi): FeaturesStore {
  let flags = $state<FeatureFlagInfo[]>([]);
  const betaFlags = $derived(flags.filter((f) => f.stage === 'beta'));
  let loading = $state(false);
  let error = $state<string | null>(null);

  return {
    get flags() {
      return flags;
    },
    get betaFlags() {
      return betaFlags;
    },
    get loading() {
      return loading;
    },
    get error() {
      return error;
    },
    async load() {
      loading = true;
      error = null;
      try {
        const res = await api.list();
        flags = res.features;
      } catch (e) {
        error = e instanceof Error ? e.message : String(e);
      } finally {
        loading = false;
      }
    },
    async setOptin(id, enabled) {
      const res = await api.setOptin(id, enabled);
      flags = res.features;
    },
  };
}

export const featuresStore = createFeaturesStore();

import type {
  AppSettings,
  CrashReportSettings,
  Stats,
  VisualSettingsPatch,
} from '$lib/api/types';
import { settingsApi } from '$lib/api/settings';
import type { VisualIndexUnit, VisualSearchStrategy } from '$lib/api/visualIndex';

/**
 * クラッシュレポート設定の既定値 (spec §7.3)。
 *
 * - `enabled: null`     = 「まだ聞かれていない」状態。`false` (明示オプトアウト)
 *                         と区別する。OptInDialog の表示判定はこの `null` で行う。
 * - `auto_prompt: true` = 既定はクラッシュ時にダイアログを自動表示する。
 * - `opted_in_at: null` = 未決定。
 *
 * backend `core/crash_reporter/settings.py::CrashReportSettings` の field 既定と
 * 完全一致させる。backend が `GET /api/settings` で `crash_report` を返さない
 * 移行期 (Sprint 7 時点) のフォールバック値として使う。
 */
const DEFAULT_CRASH_REPORT: CrashReportSettings = {
  enabled: null,
  auto_prompt: true,
  opted_in_at: null,
};

export interface SettingsStore {
  readonly settings: AppSettings | null;
  readonly stats: Stats | null;
  readonly loading: boolean;
  readonly error: string | null;
  /**
   * クラッシュレポート設定への安定アクセサ。
   * `settings?.crash_report` が undefined のときは {@link DEFAULT_CRASH_REPORT}
   * を返すため、コンシューマはガードなしで `crashReport.enabled` を読める。
   */
  readonly crashReport: CrashReportSettings;
  load(): Promise<void>;
  putOllama(default_model: string): Promise<void>;
  putVisionModel(model: string): Promise<void>;
  putVisual(patch: VisualSettingsPatch): Promise<void>;
  /**
   * クラッシュレポート設定の更新。現行値に `patch` をマージして送信し、
   * 成功時のレスポンスを store に反映する。失敗時は例外を呼び出し元へ伝播。
   */
  putCrashReport(patch: Partial<CrashReportSettings>): Promise<void>;
}

export function createSettingsStore(api = settingsApi): SettingsStore {
  let settings = $state<AppSettings | null>(null);
  let stats = $state<Stats | null>(null);
  let loading = $state(false);
  let error = $state<string | null>(null);

  const crashReport = $derived<CrashReportSettings>(
    settings?.crash_report ?? DEFAULT_CRASH_REPORT,
  );

  return {
    get settings() {
      return settings;
    },
    get stats() {
      return stats;
    },
    get loading() {
      return loading;
    },
    get error() {
      return error;
    },
    get crashReport() {
      return crashReport;
    },
    async load() {
      loading = true;
      error = null;
      try {
        const [s, st] = await Promise.all([api.get(), api.stats()]);
        settings = s;
        stats = st;
      } catch (e) {
        error = e instanceof Error ? e.message : String(e);
      } finally {
        loading = false;
      }
    },
    async putOllama(default_model: string) {
      const updated = await api.putOllama({ default_model });
      if (settings) {
        settings = { ...settings, ollama: updated };
      } else {
        await this.load();
      }
    },
    async putVisionModel(model: string) {
      const result = await api.putVisionModel(model);
      if (settings) {
        settings = { ...settings, ollama: { ...settings.ollama, vision_model: result.vision_model } };
      } else {
        await this.load();
      }
    },
    async putVisual(patch) {
      const result = await api.putVisual(patch);
      if (settings) {
        settings = { ...settings, visual: { ...settings.visual, ...result } };
      } else {
        await this.load();
      }
    },
    async putCrashReport(patch: Partial<CrashReportSettings>) {
      const merged: CrashReportSettings = {
        ...(settings?.crash_report ?? DEFAULT_CRASH_REPORT),
        ...patch,
      };
      const updated = await api.putCrashReport(merged);
      if (settings) {
        settings = { ...settings, crash_report: updated };
      } else {
        // settings が未ロードの場合は load 後に上書きしたいが、ここでは
        // 最小限に: 受け取った updated を crash_report に持つ薄い shape を
        // 構築すると他フィールドが欠落するため、再ロードを依頼する。
        await this.load();
      }
    },
  };
}

export const settingsStore = createSettingsStore();

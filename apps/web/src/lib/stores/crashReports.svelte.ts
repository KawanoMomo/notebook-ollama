/**
 * crashReports store — 未送信クラッシュレポート一覧 + 即時モーダル用スロット。
 *
 * spec: docs/specs/2026-06-28-crash-report-feedback-hub-design.md §5.6 / §8.2
 * api : apps/web/src/lib/api/crash.ts (crashApi.listPending / dismiss / markReported)
 *
 * `pending` は backend `core/crash_reporter/pending_store` の未送信レポート群を
 * そのまま反映する。`pendingCount` はフィードバックハブのヘッダバッジ計算用。
 *
 * `activeImmediate` は §5.6 即時モーダル (CrashDetectionModal) の "今表示すべき"
 * クラッシュを 1 件だけ保持するスロット。フロント errorBoundary が
 * `crashApi.report({...})` 直後に `showImmediate(crash)` を呼び、モーダル側で
 * 「今は送らない」/「プレビュー →」のどちらが押されたかに応じて
 * `clearImmediate()` する。後続クラッシュは latest-wins で上書きする
 * (古いモーダルが裏に残ると「どの例外を見ているか」が分からなくなるため)。
 *
 * 楽観削除: `dismiss(id)` と `markReported(id)` は API 呼び出し成功後に
 * ローカル配列からも除去する。失敗時は例外が呼び出し元へ伝播し、配列は
 * 変更されない (UI 側でリトライ/エラー表示する想定)。
 */
import { crashApi } from '$lib/api/crash';
import type { PendingCrash } from '$lib/api/types';

type CrashApi = Pick<typeof crashApi, 'listPending' | 'dismiss' | 'markReported'>;

export interface CrashReportsStore {
  readonly pending: PendingCrash[];
  readonly pendingCount: number;
  readonly activeImmediate: PendingCrash | null;
  /**
   * 「送信内容をプレビュー →」で開く CrashPreviewDialog の対象クラッシュ。
   * §5.6 → §5.7 への状態受け渡し。`null` の間はダイアログを mount しない。
   */
  readonly previewing: PendingCrash | null;
  load(): Promise<void>;
  dismiss(id: string): Promise<void>;
  markReported(id: string): Promise<void>;
  /** 即時モーダルに表示するクラッシュをセットする。後続呼び出しは上書き。 */
  showImmediate(crash: PendingCrash): void;
  /** 即時モーダルを閉じる (= activeImmediate を null に戻す)。 */
  clearImmediate(): void;
  /** CrashPreviewDialog を開く対象を指定する。 */
  showPreview(crash: PendingCrash): void;
  /** CrashPreviewDialog を閉じる (= previewing を null に戻す)。 */
  clearPreview(): void;
}

export function createCrashReportsStore(api: CrashApi = crashApi): CrashReportsStore {
  let pending = $state<PendingCrash[]>([]);
  const pendingCount = $derived(pending.length);
  let activeImmediate = $state<PendingCrash | null>(null);
  let previewing = $state<PendingCrash | null>(null);

  return {
    get pending() {
      return pending;
    },
    get pendingCount() {
      return pendingCount;
    },
    get activeImmediate() {
      return activeImmediate;
    },
    get previewing() {
      return previewing;
    },
    async load() {
      pending = await api.listPending();
    },
    async dismiss(id) {
      await api.dismiss(id);
      pending = pending.filter((p) => p.id !== id);
    },
    async markReported(id) {
      await api.markReported(id);
      pending = pending.filter((p) => p.id !== id);
    },
    showImmediate(crash) {
      activeImmediate = crash;
    },
    clearImmediate() {
      activeImmediate = null;
    },
    showPreview(crash) {
      previewing = crash;
    },
    clearPreview() {
      previewing = null;
    },
  };
}

export const crashReportsStore = createCrashReportsStore();

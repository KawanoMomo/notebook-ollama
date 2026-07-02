<!--
  OptInDialog — クラッシュレポート機能の初回オプトインモーダル。

  spec: docs/specs/2026-06-28-crash-report-feedback-hub-design.md §5.9
  plan: docs/superpowers/plans/2026-06-28-crash-report-feedback-hub.md Task 7.3

  ## 設計判断

  - 「常に無効」 ボタンは **絶対に出さない** (spec §5.9 明記)。
    無効化したい場合は設定画面の CrashReportSection から後で変更する経路に統一する。
  - 「後で決める」は close-only — `crash_report.enabled` を `null` のまま残し、
    次回起動・次のエラー発生時に再プロンプトする。`onDecide(false)` で親に通知する。
  - 「有効にする」は PUT `crash_report` → `onDecide(true)` の順で 2 ステップ。
    PUT が成功してから親に決定を伝えることで、親側の `settings reload` 等の
    後続処理が「すでに永続化済みの状態」を前提にできる。

  ## なぜ PUT をコンポーネント内に置くか

  CrashPreviewDialog と同じパターンを採用 (`crashApi` 注入 → 内部で API 呼び出し)。
  本ダイアログは「ユーザの明示的意思決定 + その永続化」が 1 つの責務なので、
  PUT と onDecide を分離せず 1 アクション内に閉じ込めた方が、
  「PUT は成功したが onDecide が忘れられている」「PUT 失敗時に onDecide が
  先走って親が enabled=true 前提で処理を始めてしまう」といった整合バグを防ぎやすい。

  ## エラーハンドリング

  PUT が失敗した場合は `onDecide` を呼ばずにダイアログを開いたまま残し、
  ユーザに再試行の機会を与える。エラー文言はダイアログ内に表示する
  (Toast にしないのは、ダイアログ越しに toast が見えにくいケースを避けるため)。

  ## データ保証文言の禁止

  [[feedback-no-data-guarantee-in-ui]] に従い、「送信されます/されません」等の
  保証文言は出さない。プレビューによる合意モデルへの導線を強調するに留める。

  ## アクセシビリティ

  - role="dialog" + aria-modal="true" + aria-labelledby=<title id>。
  - <details> はネイティブのキーボード/スクリーンリーダ対応に委ねる。
  - Escape は意図的にバインドしない: 「後で決める」相当のショートカットを
    Esc に割り当てると意思決定がアクシデンタルに「postpone」へ流れがちなので、
    spec §5.9 のとおり明示的なボタン押下のみを受け付ける。
-->
<script lang="ts">
  import Button from './Button.svelte';

  interface CrashReportSettingsUpdate {
    enabled: boolean;
    auto_prompt: boolean;
    /** ISO 8601 UTC timestamp. */
    opted_in_at: string;
  }

  interface OptInApi {
    putCrashReport: (body: CrashReportSettingsUpdate) => Promise<void>;
  }

  interface Props {
    /**
     * Called once the user has made an explicit decision.
     * - `false` = 「後で決める」 (postpone, settings unchanged, will re-prompt)
     * - `true`  = 「有効にする」 (PUT succeeded, settings now `enabled=true`)
     */
    onDecide: (enabled: boolean) => void;
    /**
     * Injectable API client. Defaults to a fetch-based implementation that
     * targets `PUT /api/settings/crash-report`. Tests override this so they
     * don't have to stub `globalThis.fetch` for every assertion.
     */
    api?: OptInApi;
  }

  const defaultApi: OptInApi = {
    async putCrashReport(body) {
      const res = await fetch('/api/settings/crash-report', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        throw new Error(
          `PUT /api/settings/crash-report failed with status ${res.status}`,
        );
      }
    },
  };

  let { onDecide, api = defaultApi }: Props = $props();

  let busy = $state(false);
  let errorMsg = $state<string | null>(null);

  function onPostponeClick() {
    if (busy) return;
    onDecide(false);
  }

  async function onEnableClick() {
    // Idempotency guard — second/third clicks while the PUT is in flight
    // must NOT trigger duplicate PUTs (would race opted_in_at timestamps).
    if (busy) return;
    busy = true;
    errorMsg = null;
    try {
      await api.putCrashReport({
        enabled: true,
        auto_prompt: true,
        opted_in_at: new Date().toISOString(),
      });
      onDecide(true);
    } catch (e) {
      errorMsg = e instanceof Error ? e.message : String(e);
    } finally {
      busy = false;
    }
  }
</script>

<div class="backdrop" role="presentation" data-testid="optin-backdrop">
  <div
    class="dialog"
    role="dialog"
    aria-modal="true"
    aria-labelledby="optin-dialog-title"
  >
    <header>
      <h2 id="optin-dialog-title">クラッシュレポート機能</h2>
    </header>

    <div class="body">
      <p>
        NotebookOllamaでエラーが発生したとき、開発者に不具合情報を報告できます。
      </p>
      <p>
        <strong
          >送信前にプレビューが表示され、内容を確認・編集してから送信できます。</strong
        >報告は任意です。
      </p>

      <details>
        <summary>動作の詳細を見る</summary>
        <p>
          自動検知時はモーダルでお知らせします。ヘッダ拡声器アイコンから手動で報告することもできます。
        </p>
      </details>

      {#if errorMsg}
        <p class="error" data-testid="optin-error">
          エラー: {errorMsg}
        </p>
      {/if}
    </div>

    <footer>
      <Button variant="secondary" onclick={onPostponeClick} disabled={busy}>
        後で決める
      </Button>
      <Button variant="primary" onclick={onEnableClick} disabled={busy}>
        有効にする
      </Button>
    </footer>
  </div>
</div>

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    justify-content: center;
    align-items: center;
    /* CrashDetectionModal (z-index: 200) と同階層。OptInDialog はそれと
       同時に表示されることはないため衝突しない。 */
    z-index: 200;
  }
  .dialog {
    background: var(--color-bg);
    border-radius: var(--radius-lg);
    min-width: 480px;
    max-width: 90vw;
    max-height: 90vh;
    display: flex;
    flex-direction: column;
    box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
  }
  header {
    padding: var(--space-4);
    border-bottom: 1px solid var(--color-border);
  }
  header h2 {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
    color: var(--color-fg);
  }
  .body {
    padding: var(--space-4);
    overflow: auto;
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .body p {
    margin: 0;
    font-size: 13px;
    line-height: 1.6;
    color: var(--color-fg);
  }
  details {
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-2) var(--space-3);
    background: var(--color-bg-elevated);
  }
  details summary {
    cursor: pointer;
    font-size: 12px;
    color: var(--color-fg-muted);
    user-select: none;
  }
  details[open] summary {
    margin-bottom: var(--space-2);
  }
  details p {
    font-size: 12px;
    color: var(--color-fg-muted);
    line-height: 1.5;
  }
  .error {
    padding: var(--space-2) var(--space-3);
    border-left: 3px solid var(--color-error);
    background: rgba(239, 68, 68, 0.08);
    font-size: 12px;
    color: var(--color-error);
  }
  footer {
    display: flex;
    gap: var(--space-2);
    justify-content: flex-end;
    padding: var(--space-3) var(--space-4);
    border-top: 1px solid var(--color-border);
  }
</style>

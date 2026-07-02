<!--
  CrashReportSection — 設定画面「クラッシュレポート」セクション (Sprint 7 Task 7.2)

  spec : docs/specs/2026-06-28-crash-report-feedback-hub-design.md §5.8
  plan : docs/superpowers/plans/2026-06-28-crash-report-feedback-hub.md Task 7.2

  ## レイアウト ([[feedback_compact_ui_repurpose_affordance]] 準拠)

  既存 AudioSettingsSection の `.row` / `.switch` CSS を流用し、縦に肥大化させない。

    Megaphone + 「クラッシュレポート」 + [NEW]                 ← 初回のみ
    エラー発生時、GitHubに不具合を報告できる機能です …          ← 説明文
    ─────────────────────────────────────────────────────
    [Row1] クラッシュレポート機能を有効にする           [toggle]
    [Row2] エラー発生時に自動でダイアログを表示         [toggle]
    [Row3] 未送信レポート                       [N] [確認 →]
    [Row4] サンプルレポートを見る              [プレビューを開く]

  ## 「送信される/されない」UI 文言禁止 ([[feedback_no_data_guarantee_in_ui]])

  toggle ラベルは「機能を有効にする」「ダイアログを表示」までに留め、
  「送信される/送信されない」の保証文言は一切出さない。送信内容の合意は
  CrashPreviewDialog のプレビュー画面で取る (spec §6.1)。

  ## NEW バッジ

  localStorage `crashreport_nav_seen` が立っていない場合のみ描画。
  描画と同時にフラグを立てるため、2 回目以降の表示では出ない。
  本機能リリース直後の発見性を上げる用途で、設定アクセスの妨げにならない。

  ## DI

  `settings` / `hub` / `crashes` props で各 store を差し替え可能。
  default は global singleton。ユニットテストでは独立インスタンスを渡して
  グローバル状態の漏れを防ぐ (NoticesTab と同じパターン)。
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { Megaphone } from '@lucide/svelte';

  import {
    settingsStore,
    type SettingsStore,
  } from '$lib/stores/settings.svelte';
  import {
    feedbackHubStore,
    type FeedbackHubStore,
  } from '$lib/stores/feedbackHub.svelte';
  import {
    crashReportsStore,
    type CrashReportsStore,
  } from '$lib/stores/crashReports.svelte';
  import { pushToast } from '$lib/components/Toast.svelte';
  import type { PendingCrash } from '$lib/api/types';

  interface Props {
    settings?: SettingsStore;
    hub?: FeedbackHubStore;
    crashes?: CrashReportsStore;
  }
  let {
    settings = settingsStore,
    hub = feedbackHubStore,
    crashes = crashReportsStore,
  }: Props = $props();

  const NAV_SEEN_KEY = 'crashreport_nav_seen';

  // NEW バッジは初回 mount 時のみ表示し、フラグを立てて以降は出さない。
  // SSR / prerender 環境で localStorage が未定義の場合は false に倒す。
  let showNewBadge = $state(false);

  onMount(() => {
    try {
      if (typeof localStorage === 'undefined') return;
      if (!localStorage.getItem(NAV_SEEN_KEY)) {
        showNewBadge = true;
        localStorage.setItem(NAV_SEEN_KEY, '1');
      }
    } catch {
      // localStorage アクセス失敗 (private mode / quota) は黙殺。
      // バッジが出ない/フラグが立たない側にフォールバックする。
    }
  });

  // crash_report 設定は store の crashReport derived 経由で読む。
  // settings.settings が null (未ロード) でも DEFAULT_CRASH_REPORT が返るので
  // ガード不要。enabled=null は「未決定」だが、UI 上は OFF として表示する
  // (Task 7.3 OptInDialog 側で「未決定」を別途扱う)。
  const enabledOn = $derived(settings.crashReport.enabled === true);
  const autoPromptOn = $derived(settings.crashReport.auto_prompt === true);

  let togglingEnabled = $state(false);
  let togglingAuto = $state(false);

  async function toggleEnabled() {
    if (togglingEnabled) return;
    togglingEnabled = true;
    const next = !enabledOn;
    try {
      await settings.putCrashReport({
        enabled: next,
        auto_prompt: settings.crashReport.auto_prompt,
        opted_in_at: settings.crashReport.opted_in_at,
      });
    } catch (e) {
      pushToast(
        e instanceof Error ? e.message : String(e),
        'error',
      );
    } finally {
      togglingEnabled = false;
    }
  }

  async function toggleAutoPrompt() {
    if (togglingAuto) return;
    togglingAuto = true;
    const next = !autoPromptOn;
    try {
      // enabled は独立にトグルできるため、現行値を保持して送る。
      await settings.putCrashReport({
        enabled: settings.crashReport.enabled,
        auto_prompt: next,
        opted_in_at: settings.crashReport.opted_in_at,
      });
    } catch (e) {
      pushToast(
        e instanceof Error ? e.message : String(e),
        'error',
      );
    } finally {
      togglingAuto = false;
    }
  }

  function openBugsTab() {
    hub.setTab('bugs');
    hub.open();
  }

  /**
   * 設定画面から「サンプルレポートを見る」で起動するダミー PendingCrash。
   *
   * 実クラッシュ由来でない (収集器を通っていない) ため、安全に固定値で
   * 構築できる。CrashPreviewDialog 側は backend `GET /api/crash/{id}/prefill-url`
   * を叩いて prefill を取りに行く設計なので、本サンプルは backend に存在しない
   * id を持つ。プレビューダイアログは見た目確認用途に留め、「GitHubで開く」
   * を押されたとしても 404 で済むよう、CrashPreviewDialog は loadError を
   * 画面に出す (本サンプル用にエンドポイントを増やさない判断)。
   */
  function buildSamplePending(): PendingCrash {
    return {
      id: 'sample-crash-preview',
      fingerprint: '0'.repeat(40),
      created_at: new Date().toISOString(),
      exception_type: 'RuntimeError',
      exception_message:
        'サンプルクラッシュ: これは設定画面から開いたプレビュー用ダミーです',
      trace: [
        '  File "apps/api/main.py", line 42, in main',
        '    raise RuntimeError("サンプル")',
        'RuntimeError: サンプル',
      ],
      hardware: {
        cpu_model: 'Intel(R) Core(TM) i9-12900KF',
        cpu_cores: 16,
        cpu_threads: 24,
        ram_total_gb: 32,
        ram_available_gb: 20,
        gpu_model: 'NVIDIA GeForce RTX 2080 Ti',
        gpu_vram_mb: 11264,
        driver_version: '555.42',
        disk_free_gb: 500,
        os_platform: 'Windows-11',
        python_version: '3.12.0',
      },
      log_tail: [
        {
          level: 'INFO',
          event_name: 'app.startup',
          timestamp: '2026-06-28T00:00:00Z',
        },
      ],
      source: 'frontend',
    };
  }

  function openSamplePreview() {
    crashes.showPreview(buildSamplePending());
  }
</script>

<div class="head">
  <h3>
    <Megaphone size={18} strokeWidth={1.75} aria-hidden="true" />
    クラッシュレポート
    {#if showNewBadge}
      <span class="new-badge" aria-label="新機能">NEW</span>
    {/if}
  </h3>
  <p class="sub">
    エラー発生時、GitHubに不具合を報告できる機能です。送信前にプレビュー画面で内容を確認・編集できます。
  </p>
</div>

<div class="group">
  <div class="row">
    <div class="lab">
      クラッシュレポート機能を有効にする
      <small>ヘッダの拡声器から「不具合」タブを開けば、未送信レポートを後から確認できます。</small>
    </div>
    <div class="ctl">
      <button
        type="button"
        class="switch"
        class:off={!enabledOn}
        role="switch"
        aria-checked={enabledOn}
        aria-label="クラッシュレポート機能を有効にする"
        disabled={togglingEnabled}
        onclick={toggleEnabled}
      ><i></i></button>
    </div>
  </div>

  <div class="row">
    <div class="lab">
      エラー発生時に自動でダイアログを表示
      <small>OFF にしても未送信レポートは内部に溜まり、ヘッダの拡声器 → 不具合タブから確認できます。</small>
    </div>
    <div class="ctl">
      <button
        type="button"
        class="switch"
        class:off={!autoPromptOn}
        role="switch"
        aria-checked={autoPromptOn}
        aria-label="エラー発生時に自動でダイアログを表示"
        disabled={togglingAuto}
        onclick={toggleAutoPrompt}
      ><i></i></button>
    </div>
  </div>

  <div class="row">
    <div class="lab">
      未送信レポート
      <small>溜まっているクラッシュレポートをフィードバックハブの「不具合」タブで確認します。</small>
    </div>
    <div class="ctl">
      <span class="badge" data-testid="crash-pending-badge">
        {crashes.pendingCount}
      </span>
      <button
        type="button"
        class="btn"
        onclick={openBugsTab}
      >確認 →</button>
    </div>
  </div>

  <div class="row">
    <div class="lab">
      サンプルレポートを見る
      <small>送信前に表示されるプレビュー画面の見た目を確認できます。</small>
    </div>
    <div class="ctl">
      <button
        type="button"
        class="btn"
        onclick={openSamplePreview}
      >プレビューを開く</button>
    </div>
  </div>
</div>

<style>
  .head {
    margin-bottom: 14px;
  }

  h3 {
    margin: 0 0 var(--space-1);
    font-size: 17px;
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }

  .new-badge {
    background: var(--color-accent);
    color: #fff;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.04em;
    border-radius: 999px;
    padding: 2px 7px;
    line-height: 1.4;
  }

  .sub {
    color: var(--color-fg-muted);
    font-size: 12px;
    margin: 0;
    line-height: 1.6;
  }

  .group {
    margin-top: 12px;
  }

  .row {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 10px 18px;
    align-items: center;
    padding: 10px 0;
  }

  .row + .row {
    border-top: 1px solid #f0f0f2;
  }

  .lab {
    font-size: 13px;
  }

  .lab small {
    display: block;
    color: var(--color-fg-muted);
    font-size: 11px;
    margin-top: 2px;
    font-weight: 400;
    line-height: 1.5;
  }

  .ctl {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    justify-content: flex-end;
  }

  /* AudioSettingsSection と同じ switch トークン */
  .switch {
    width: 40px;
    height: 23px;
    border-radius: 999px;
    background: var(--color-accent);
    position: relative;
    flex: none;
    border: none;
    padding: 0;
    cursor: pointer;
  }

  .switch.off {
    background: #c8c8cd;
  }

  .switch:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .switch i {
    position: absolute;
    top: 2px;
    width: 19px;
    height: 19px;
    border-radius: 50%;
    background: #fff;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
    right: 2px;
    transition: right 0.12s, left 0.12s;
  }

  .switch.off i {
    right: auto;
    left: 2px;
  }

  .badge {
    background: var(--color-bg-elevated);
    color: var(--color-fg);
    font-size: 12px;
    font-weight: 600;
    border-radius: 999px;
    padding: 2px 9px;
    min-width: 24px;
    text-align: center;
  }

  .btn {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    border: 1px solid var(--color-border);
    background: var(--color-bg);
    color: var(--color-fg);
    border-radius: var(--radius-md);
    padding: 6px 11px;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
  }

  .btn:hover {
    background: var(--color-bg-elevated);
  }
</style>

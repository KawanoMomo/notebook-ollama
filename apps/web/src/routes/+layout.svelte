<script lang="ts">
  import '../app.css';
  import { onMount, onDestroy } from 'svelte';
  import AppHeader from '$lib/components/AppHeader.svelte';
  import Toast from '$lib/components/Toast.svelte';
  import NotebookSwitcher from '$lib/components/NotebookSwitcher.svelte';
  import FeedbackHubDrawer from '$lib/components/FeedbackHubDrawer.svelte';
  import CrashDetectionModal from '$lib/components/CrashDetectionModal.svelte';
  import CrashPreviewDialog from '$lib/components/CrashPreviewDialog.svelte';
  import OptInDialog from '$lib/components/OptInDialog.svelte';
  import { bindShortcuts } from '$lib/utils/keys';
  import { initErrorBoundary } from '$lib/utils/errorBoundary';
  import { afterNavigate } from '$app/navigation';
  import { navMemoryStore } from '$lib/stores/navMemory.svelte';
  import { feedbackHubStore } from '$lib/stores/feedbackHub.svelte';
  import { crashReportsStore } from '$lib/stores/crashReports.svelte';
  import { settingsStore } from '$lib/stores/settings.svelte';
  import { featuresStore } from '$lib/stores/features.svelte';
  import { devmode } from '$lib/stores/devmode.svelte';
  import DevPanel from '$lib/components/DevPanel.svelte';
  import { noticesStore } from '$lib/stores/notices.svelte';
  import { crashApi, type CrashReportInput } from '$lib/api/crash';

  let { children } = $props();
  let switcherOpen = $state(false);
  let unbindShortcuts: (() => void) | null = null;
  // initErrorBoundary returns its own unbind; we keep them separate so HMR /
  // teardown can clean each up independently (and so a regression in one
  // can't silently leak listeners from the other).
  let unbindErrorBoundary: (() => void) | null = null;

  // -----------------------------------------------------------------------
  // OptInDialog 表示制御 (Sprint 7 Task 7.3 — spec §5.9, verify-7.3 fix)
  //
  // 「設定がロードされており、かつ `crash_report.enabled === null` (未決定)」
  // のとき、初回 1500ms 後に OptInDialog を出す。1500ms 待つのは「最初の
  // 描画 = ノート/録音の画面」をユーザに見せてから割り込むため
  // (hijacking 回避)。
  //
  // ## 初版の不具合 (verify-7.3) と修正
  //
  // 初版は `onMount` 内で単発の `setTimeout(showOptInIfStillUndecided, 1500)`
  // を撃つだけだった。これには 2 つの不具合があった:
  //
  //   1. **遅い settings ロード (>1500ms) で永久に出ない。** 1500ms 時点で
  //      `settings === null` だと early-return し、その後 settings が
  //      `enabled === null` でロードされても再アームしないため、その session
  //      中ずっとダイアログが出ない (次回起動を待つしかない)。
  //
  //   2. **error-first トリガなし。** `enabled === null` のまま 1500ms 以内に
  //      エラーが起きても OptInDialog ではなく (本来表示できない)
  //      CrashDetectionModal が走ろうとして無音で 403 され、ユーザは
  //      何が起きたか分からない。
  //
  // 修正:
  //
  //   - **$effect で再アーム。** `settingsStore.settings` を watch し、
  //     「ロード済 + enabled===null」になった瞬間に 1500ms タイマーを仕掛ける。
  //     enabled が非 null に flip したらキャンセル。`optInArmed` で 1 回しか
  //     仕掛けないようにする (再アームは「未→未」遷移では起きない)。
  //
  //   - **error-first キュー。** errorBoundary に `onOptInPending(payload)`
  //     コールバックを渡し、enabled===null 時の crash payload をここで queue
  //     して即座に OptInDialog を出す (1500ms 待たない)。
  //     - 「有効にする」: PUT 成功後、queue した payload を `crashApi.reportFrontendCrash`
  //       で再送 → 戻った PendingCrash を `crashReportsStore.showImmediate` に流し、
  //       CrashDetectionModal に handoff。
  //     - 「後で決める」: queue を破棄 (session 中はもう表示しない)。
  //
  //   - **postponedThisSession** は維持: 「後で決める」を押した session 中は
  //     timer も error-first も再起動しない (next session で再判定)。
  // -----------------------------------------------------------------------
  let optInOpen = $state(false);
  let postponedThisSession = $state(false);
  /**
   * Pending error payload from errorBoundary while opt-in is undecided.
   * 「有効にする」 で {@link drainQueuedCrash} が拾って backend に再送する。
   * 「後で決める」で破棄。最新のものだけを保持 (latest-wins、上書きで OK):
   * ユーザは「直前にどんなエラーが起きてダイアログが出たか」を覚えていれば
   * 十分で、古いキュー要素を貯めても結局 1 件しか UI に出せない。
   */
  let queuedCrashPayload: CrashReportInput | null = $state(null);
  let optInInitialTimer: ReturnType<typeof setTimeout> | null = null;
  /**
   * `true` once we've scheduled or fired the 1500ms timer for the current
   * session. Prevents the `$effect` from re-scheduling on every reactive
   * read (the effect watches settings — re-running on unrelated settings
   * fields would otherwise restart the timer indefinitely).
   */
  let optInArmed = $state(false);
  const OPT_IN_INITIAL_DELAY_MS = 1500;

  function showOptInIfStillUndecided() {
    if (postponedThisSession) return;
    // settings がロードされていない (settings === null) ときはスキップする。
    // crashReport derived は default に倒れるため enabled === null になるが、
    // 「未ロード」を「未決定」と誤判定してダイアログを誤爆させない。
    if (settingsStore.settings === null) return;
    if (settingsStore.crashReport.enabled !== null) return;
    optInOpen = true;
  }

  function cancelOptInTimer() {
    if (optInInitialTimer !== null) {
      clearTimeout(optInInitialTimer);
      optInInitialTimer = null;
    }
  }

  function getOptInState(): 'enabled' | 'disabled' | 'undecided' | 'unloaded' {
    if (settingsStore.settings === null) return 'unloaded';
    const e = settingsStore.crashReport.enabled;
    if (e === null) return 'undecided';
    return e ? 'enabled' : 'disabled';
  }

  /**
   * Called by errorBoundary when `enabled === null` and a crash fires.
   * Queue the payload and open OptInDialog immediately (error-first path,
   * spec §5.9). Latest-wins: a newer error overwrites the queued one.
   */
  function onOptInPending(payload: CrashReportInput) {
    if (postponedThisSession) return;
    queuedCrashPayload = payload;
    optInOpen = true;
    // The initial-arm timer is now redundant (the dialog is already open),
    // but we leave it alone — if the user dismisses without deciding we'd
    // still want it to fire next time. In practice the dialog stays open
    // until the user clicks one of the two buttons.
  }

  /**
   * After 「有効にする」: re-POST the queued payload (which the boundary
   * previously short-circuited) and hand the resulting `PendingCrash` to
   * `crashReportsStore.showImmediate` so `CrashDetectionModal` mounts.
   *
   * Best-effort: a failure here doesn't roll back the opt-in. We log via
   * `console.warn` so a developer running DevTools open sees it, but the
   * user still successfully opted in. The next crash will land via the
   * normal boundary path.
   */
  async function drainQueuedCrash(payload: CrashReportInput): Promise<void> {
    try {
      const created = await crashApi.reportFrontendCrash(payload);
      crashReportsStore.showImmediate(created);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn('[layout] queued crash replay failed', err);
    }
  }

  async function handleOptInDecide(enabled: boolean) {
    optInOpen = false;
    if (enabled) {
      // 「有効にする」: PUT は OptInDialog 内で完了済み。
      // 後続の queue 処理が走るよう、関連 store を refetch する。
      // Promise.allSettled で 1 つ落ちても他の reload は走らせる
      // (settings は新値が必要、crashes/notices は best-effort)。
      await Promise.allSettled([
        settingsStore.load(),
        crashReportsStore.load(),
        noticesStore.load(),
      ]);
      // Drain after settings reload so the boundary's gate (which reads live
      // settings.crashReport.enabled) would also accept this POST if it came
      // through the normal path — i.e. we're consistent with the gate's
      // truth table even though we bypass it here.
      const queued = queuedCrashPayload;
      queuedCrashPayload = null;
      if (queued !== null) {
        await drainQueuedCrash(queued);
      }
    } else {
      // 「後で決める」: 設定は触らない。今 session では再プロンプトしない。
      postponedThisSession = true;
      cancelOptInTimer();
      // Drop the queued error too — the user said "later" so we don't want
      // it to silently fire next time the dialog opens (which would be next
      // session anyway, by definition of postponedThisSession).
      queuedCrashPayload = null;
    }
  }

  // -----------------------------------------------------------------------
  // Re-arm effect (verify-7.3 fix #1 / #2)
  // -----------------------------------------------------------------------
  //
  // Watch `settingsStore.settings` — when it transitions into "loaded with
  // enabled===null" schedule the 1500ms timer. If it transitions into a
  // non-null enabled value, cancel any pending timer. Use `optInArmed` to
  // avoid re-scheduling on every reactive read.
  //
  // This effect runs once on mount (settings===null → no-op) and again
  // whenever `settings` or the derived `crashReport` changes.
  $effect(() => {
    if (postponedThisSession) return;
    const s = settingsStore.settings;
    if (s === null) return; // still loading; wait for the load to complete
    const enabled = settingsStore.crashReport.enabled;
    if (enabled !== null) {
      // User has answered (true or false). Cancel any pending arm and
      // ensure we never schedule again.
      cancelOptInTimer();
      optInArmed = true; // suppress future scheduling
      return;
    }
    // Loaded + undecided. Schedule the initial-arm timer once.
    if (optInArmed) return;
    optInArmed = true;
    optInInitialTimer = setTimeout(() => {
      optInInitialTimer = null;
      showOptInIfStillUndecided();
    }, OPT_IN_INITIAL_DELAY_MS);
  });

  onMount(() => {
    // S7 home-route fix: eagerly load settings at the layout level so the
    // errorBoundary's gate sees the live `crashReport.enabled` value the
    // first time a crash fires — regardless of which route the user landed
    // on. Without this, on routes that don't call `settingsStore.load()`
    // themselves (e.g. `/`, modal-only screens), `settings === null` for the
    // whole session. The boundary's derived `crashReport.enabled` then
    // permanently reads `null` (DEFAULT_CRASH_REPORT fallback) which:
    //   - routes through `onOptInPending` → opens OptInDialog for users who
    //     are actually opted in (backend has `enabled: true` persisted), AND
    //   - skips POST /api/crash/report entirely → CrashDetectionModal never
    //     mounts even though the user wanted the prompt.
    // This was the S7 evaluator's "CrashDetectionModal が出ない on `/`" repro.
    //
    // Fire-and-forget: the boundary has its own loading gate as defense-in-
    // depth for the race window between this call and its resolution, so we
    // don't need to await before wiring `initErrorBoundary` below.
    void settingsStore.load();
    // ベータ機能フラグもレイアウトレベルで読み込む。設定画面の onMount だけに
    // 頼ると、ノートブック画面(再取込ボタン・表HTML表示の判定に使う)では
    // featuresStore.flags が空のままになってしまう。
    void featuresStore.load();

    unbindShortcuts = bindShortcuts([
      {
        combo: 'Mod+k',
        handler: () => (switcherOpen = true),
      },
    ]);
    // Wire frontend crash auto-detection (Sprint 5 Task 5.8). Without this
    // call, `window.error` / `unhandledrejection` go nowhere and the entire
    // CrashDetectionModal pipeline is dark in production.
    //
    // Sprint 7 (verify-7.3): pass `onOptInPending` so the boundary can hand
    // crash payloads to us while `enabled === null`. We queue + open
    // OptInDialog immediately (error-first path, spec §5.9).
    unbindErrorBoundary = initErrorBoundary({
      onOptInPending,
    });
  });
  onDestroy(() => {
    unbindShortcuts?.();
    unbindErrorBoundary?.();
    cancelOptInTimer();
  });

  // Expose getOptInState for any consumer (tests / future routes) that
  // wants the same triage logic the boundary already gets via the gate.
  // Currently unused inside this file but kept exported-shaped to make the
  // contract greppable.
  void getOptInState;

  // 開発者モード: BE 設定値を devmode ストアへ同期する(OFF 遷移で
  // unlocked / panelOpen が強制リセットされる。spec §5.1 / §10.1)。
  $effect(() => {
    const s = settingsStore.settings;
    if (s !== null) devmode.syncEnabled(s.dev?.enabled ?? false);
  });

  // 各遷移完了時に「設定以外」の現在パスを記録し、設定からの戻り先にする。
  afterNavigate((nav) => {
    const path = nav.to?.url.pathname;
    if (path) navMemoryStore.record(path);
  });
</script>

<AppHeader />
<main>
  {@render children()}
</main>
<Toast />

{#if switcherOpen}
  <NotebookSwitcher onClose={() => (switcherOpen = false)} />
{/if}

{#if feedbackHubStore.drawerOpen}
  <FeedbackHubDrawer />
{/if}

{#if crashReportsStore.activeImmediate}
  {@const activeCrash = crashReportsStore.activeImmediate}
  <CrashDetectionModal
    crash={activeCrash}
    onDismiss={() => crashReportsStore.clearImmediate()}
    onPreview={(crash) => {
      // §5.6 → §5.7 ハンドオフ: 即時モーダルを閉じ、previewing スロットに
      // 同じクラッシュをセットして CrashPreviewDialog をマウントする。
      crashReportsStore.showPreview(crash);
      crashReportsStore.clearImmediate();
    }}
  />
{/if}

{#if crashReportsStore.previewing}
  {@const previewCrash = crashReportsStore.previewing}
  <CrashPreviewDialog
    crash={previewCrash}
    onClose={() => crashReportsStore.clearPreview()}
    onDismissed={() => crashReportsStore.clearPreview()}
    onReported={() => crashReportsStore.clearPreview()}
  />
{/if}

<!--
  OptInDialog: spec §5.9 初回オプトインモーダル。
  - 起動 1500ms 後 (settings ロード後の再アーム時刻 = $effect 起算)
    に `crash_report.enabled === null` ならマウント。
  - errorBoundary が error-first パスで `onOptInPending` を呼んだ場合は
    1500ms 待たずに即座にマウントする (latest crash を queue 済み)。
  - 同時に CrashDetectionModal が出るケースは backend 403 で抑止される
    ため、ここでは +layout 側 gating せず単純に独立マウントする。
-->
{#if optInOpen}
  <OptInDialog onDecide={handleOptInDecide} />
{/if}

{#if devmode.panelOpen}
  <DevPanel />
{/if}

<style>
  main {
    min-height: calc(100vh - var(--header-height));
  }
</style>

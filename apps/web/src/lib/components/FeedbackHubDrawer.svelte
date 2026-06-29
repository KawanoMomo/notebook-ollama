<script lang="ts">
  /**
   * FeedbackHubDrawer — 右側 440px Drawer (枠 + 3 タブ切替のみ)。
   *
   * spec : docs/specs/2026-06-28-crash-report-feedback-hub-design.md §5.2
   * plan : docs/superpowers/plans/2026-06-28-crash-report-feedback-hub-design ... Task 5.5
   *
   * Sprint 5 のスコープ:
   * - backdrop click + ESC で close (既存 Modal.svelte と同じパターン)
   * - 3 underline タブ「お知らせ / 不具合 / ご意見」を feedbackHubStore.activeTab と接続
   * - 不具合タブのみ pendingCount > 0 のとき pill を表示 (Sprint 5 で取得済データ)
   * - タブ内容は Sprint 6/7/8 で実装する placeholder (NoticesTab / BugReportTab / FeedbackTab)
   *
   * テスト容易性のため `hub` / `crashes` は props で DI 可能 (default は global singleton)。
   * 通常は +layout.svelte が `{#if feedbackHubStore.drawerOpen}<FeedbackHubDrawer />{/if}`
   * で mount する。
   */
  import { X } from '@lucide/svelte';
  import { onMount, tick } from 'svelte';
  import { fly } from 'svelte/transition';
  import {
    feedbackHubStore,
    type FeedbackHubStore,
    type FeedbackHubTab,
  } from '$lib/stores/feedbackHub.svelte';
  import {
    crashReportsStore,
    type CrashReportsStore,
  } from '$lib/stores/crashReports.svelte';
  import { noticesStore, type NoticesStore } from '$lib/stores/notices.svelte';
  import NoticesTab from './feedback-hub/NoticesTab.svelte';
  import BugReportTab from './feedback-hub/BugReportTab.svelte';
  import FeedbackTab from './feedback-hub/FeedbackTab.svelte';

  interface Props {
    hub?: FeedbackHubStore;
    crashes?: CrashReportsStore;
    /**
     * Sprint 6: NoticesTab が消費する store。テストでモック API を持つ
     * インスタンスを注入できるよう prop で渡す。default は global singleton。
     */
    notices?: NoticesStore;
  }
  let {
    hub = feedbackHubStore,
    crashes = crashReportsStore,
    notices = noticesStore,
  }: Props = $props();

  const TITLE = 'お知らせ・フィードバック';

  // 各タブの label / 表示用 pill 数値 (Sprint 5 では bugs のみ pendingCount)。
  const tabs: { id: FeedbackHubTab; label: string }[] = [
    { id: 'notices', label: 'お知らせ' },
    { id: 'bugs', label: '不具合' },
    { id: 'feedback', label: 'ご意見' },
  ];

  function pillFor(id: FeedbackHubTab): number {
    if (id === 'bugs') return crashes.pendingCount;
    return 0;
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') hub.close();
  }

  // --- Accessibility: focus management (spec §5.2) -------------------------
  // Adversarial review found Tab never entered the drawer (focus stayed in
  // the header chrome). Fix = auto-focus the close button on open + a Tab /
  // Shift+Tab focus trap that wraps focus inside the drawer.
  let closeBtnEl = $state<HTMLButtonElement | null>(null);
  let drawerEl = $state<HTMLElement | null>(null);

  onMount(() => {
    // Wait one tick so `bind:this` is resolved before focusing.
    tick().then(() => closeBtnEl?.focus());
  });

  function focusableInDrawer(): HTMLElement[] {
    if (!drawerEl) return [];
    // Match common keyboard-tabbable elements; exclude disabled or tabindex="-1".
    const sel =
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    return Array.from(drawerEl.querySelectorAll<HTMLElement>(sel));
  }

  function trapTab(e: KeyboardEvent) {
    if (e.key !== 'Tab') return;
    const els = focusableInDrawer();
    if (els.length === 0) return;
    const first = els[0];
    const last = els[els.length - 1];
    const active = document.activeElement as HTMLElement | null;
    if (e.shiftKey && active === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
    // Otherwise let the browser handle normal forward/backward movement.
  }
</script>

<svelte:window onkeydown={onKey} />

<div class="backdrop" onclick={() => hub.close()} role="presentation">
  <div
    bind:this={drawerEl}
    class="drawer"
    role="dialog"
    aria-modal="true"
    aria-label={TITLE}
    onclick={(e) => e.stopPropagation()}
    onkeydown={trapTab}
    transition:fly={{ x: 440, duration: 180 }}
  >
    <header>
      <h2>{TITLE}</h2>
      <button
        bind:this={closeBtnEl}
        class="close"
        aria-label="閉じる"
        onclick={() => hub.close()}
      >
        <X size={18} />
      </button>
    </header>

    <div class="tabs" role="tablist">
      {#each tabs as t (t.id)}
        {@const active = hub.activeTab === t.id}
        {@const pill = pillFor(t.id)}
        <button
          type="button"
          role="tab"
          aria-selected={active ? 'true' : 'false'}
          class="tab"
          class:active
          onclick={() => hub.setTab(t.id)}
        >
          <span class="label">{t.label}</span>
          {#if pill > 0}
            <span class="pill" class:pill-active={active}>{pill}</span>
          {/if}
        </button>
      {/each}
    </div>

    <div class="panel" role="tabpanel">
      {#if hub.activeTab === 'notices'}
        <NoticesTab store={notices} />
      {:else if hub.activeTab === 'bugs'}
        <!-- Sprint 7: NoticesTab と同じ DI 流儀で crashes ストアを prop で注入する。
             これにより drawer 側で createCrashReportsStore(mockApi) を作って
             BugReportTab の挙動を完全制御できる (global singleton への副作用なし)。 -->
        <BugReportTab store={crashes} />
      {:else if hub.activeTab === 'feedback'}
        <FeedbackTab />
      {/if}
    </div>
  </div>
</div>

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    /* spec §5.2: rgba(11, 13, 18, 0.35) */
    background: rgba(11, 13, 18, 0.35);
    z-index: 150;
    display: flex;
    justify-content: flex-end;
    align-items: stretch;
  }
  .drawer {
    /* spec §5.2: 幅 440px / フル高さ / 背景 #fff / 左影 */
    /* スライドイン演出は Svelte `transition:fly` で実装 (180ms / x=440)。
       かつての `transform: translateX(0)` + `transition: transform` は
       transform が変わらないため死んでおり、ドロワーが瞬間表示されていた。 */
    width: 440px;
    max-width: 100vw;
    height: 100vh;
    background: #fff;
    box-shadow: -8px 0 32px rgba(11, 13, 18, 0.08);
    display: flex;
    flex-direction: column;
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-4);
    border-bottom: 1px solid #e5e7eb;
  }
  header h2 {
    margin: 0;
    font-size: 18px;
    font-weight: 600;
    letter-spacing: -0.01em;
  }
  .close {
    background: none;
    border: none;
    color: var(--color-fg-muted);
    padding: var(--space-1);
    border-radius: var(--radius-sm);
  }
  .close:hover {
    background: var(--color-bg-elevated);
  }

  .tabs {
    display: flex;
    gap: var(--space-3);
    padding: 0 var(--space-4);
    border-bottom: 1px solid #e5e7eb;
  }
  .tab {
    background: none;
    border: none;
    padding: var(--space-3) var(--space-1);
    font-size: 13px;
    font-weight: 500;
    color: #6b7280;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
  }
  .tab:hover {
    color: #0b0d12;
  }
  .tab.active {
    color: #0b0d12;
    border-bottom-color: #0b0d12;
  }
  .pill {
    display: inline-flex;
    min-width: 18px;
    height: 18px;
    align-items: center;
    justify-content: center;
    padding: 0 6px;
    font-size: 11px;
    font-weight: 600;
    border-radius: 9999px;
    background: #e5e7eb;
    color: #0b0d12;
  }
  .pill.pill-active {
    background: #0b0d12;
    color: #fff;
  }

  .panel {
    flex: 1;
    overflow-y: auto;
  }
</style>

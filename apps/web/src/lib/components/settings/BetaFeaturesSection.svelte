<!--
  BetaFeaturesSection — 設定画面「ベータ機能」セクション (Task 4)

  spec : docs/specs/2026-07-20-beta-feature-flags-design.md
  plan : Sprint A Task 4

  ## レイアウト (CrashReportSection.svelte 準拠)

  既存 CrashReportSection の `.head` / `.group` / `.row` / `.switch` CSS を
  流用し、縦に肥大化させない ([[feedback_compact_ui_repurpose_affordance]])。

    FlaskConical + 「ベータ機能」
    評価中の機能です。有効化するとこのアプリでのみ提供されます。
    ─────────────────────────────────────────────────────
    [Row per flag] name (+ description)              [toggle]

  ## 空件数ガード

  `betaFlags` が 0 件の場合は何も描画しない(stage === 'ga' に昇格して
  ベータフラグが尽きた場合を含む)。ナビ側 (+page.svelte) も同条件で
  ナビ項目自体を隠す。

  ## GA フラグの扱い

  `stage === 'ga'` はサーバ側でオプトイン変更を拒否するため一覧から除外する
  (`betaFlags` は features store 側で `stage === 'beta'` のみに絞り込み済み)。

  ## DI

  `features` prop で store を差し替え可能。default は global singleton。
-->
<script lang="ts">
  import { FlaskConical } from '@lucide/svelte';

  import { featuresStore, type FeaturesStore } from '$lib/stores/features.svelte';
  import { pushToast } from '$lib/components/Toast.svelte';

  interface Props {
    features?: FeaturesStore;
  }
  let { features = featuresStore }: Props = $props();

  let togglingId = $state<string | null>(null);

  async function toggle(id: string, next: boolean) {
    if (togglingId) return;
    togglingId = id;
    try {
      await features.setOptin(id, next);
    } catch (e) {
      pushToast(e instanceof Error ? e.message : String(e), 'error');
    } finally {
      togglingId = null;
    }
  }
</script>

{#if features.betaFlags.length > 0}
  <div class="head">
    <h3>
      <FlaskConical size={18} strokeWidth={1.75} aria-hidden="true" />
      ベータ機能
    </h3>
    <p class="sub">評価中の機能です。有効化するとこのアプリでのみ提供されます。</p>
  </div>

  <div class="group">
    {#each features.betaFlags as flag (flag.id)}
      <div class="row">
        <div class="lab">
          {flag.name}
          <small>{flag.description}</small>
        </div>
        <div class="ctl">
          <button
            type="button"
            class="switch"
            class:off={!flag.enabled}
            role="switch"
            aria-checked={flag.enabled}
            aria-label={flag.name}
            disabled={togglingId === flag.id}
            onclick={() => toggle(flag.id, !flag.enabled)}
          ><i></i></button>
        </div>
      </div>
    {/each}
  </div>
{/if}

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

  /* AudioSettingsSection / CrashReportSection と同じ switch トークン */
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
</style>

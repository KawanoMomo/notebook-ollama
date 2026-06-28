<script lang="ts">
  import { Square } from '@lucide/svelte';
  import { recordingStore } from '$lib/stores/recording.svelte';
  import { pushToast } from './Toast.svelte';

  interface Props {
    // Accepted for symmetry with SourcesPanel and future per-notebook gain
    // controls; the recording lifecycle itself is owned by recordingStore.
    notebookId: string;
  }
  let {}: Props = $props();

  let elapsed = $derived(formatElapsed(recordingStore.elapsedMs));

  function formatElapsed(ms: number): string {
    const total = Math.floor(ms / 1000);
    const m = Math.floor(total / 60)
      .toString()
      .padStart(2, '0');
    const s = (total % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  }

  function toggleLive() {
    recordingStore.toggleLiveCaption();
  }

  async function stop() {
    try {
      await recordingStore.stop();
    } catch (e) {
      pushToast(e instanceof Error ? e.message : String(e), 'error');
    }
  }
</script>

<div class="recstrip">
  {#if recordingStore.recording}
    <div class="recrow">
      <span class="recnow"><span class="dot pulse"></span> 録音中</span>
      <span class="rectimer">{elapsed}</span>
      <button class="stopbtn" onclick={stop}>
        <Square size="12" fill="currentColor" /> 停止
      </button>
    </div>
    <div class="recrow">
      <span class="live-pill">ライブ字幕</span>
      <button
        class="switch"
        class:off={!recordingStore.liveCaptionEnabled}
        style="margin-left:auto"
        role="switch"
        aria-checked={recordingStore.liveCaptionEnabled}
        aria-label="ライブ字幕"
        onclick={toggleLive}
      >
        <i></i>
      </button>
    </div>
    <div class="minimeters">
      <span aria-hidden="true">🎤</span>
      <div class="mini"><i style="width:{Math.round(recordingStore.micLevel * 100)}%"></i></div>
      <span aria-hidden="true">🔊</span>
      <div class="mini"><i style="width:{Math.round(recordingStore.sysLevel * 100)}%"></i></div>
    </div>
  {:else}
    <div class="recrow">
      <span class="live-pill">ライブ字幕</span>
      <span class="hint">録音中に字幕表示</span>
      <button
        class="switch"
        class:off={!recordingStore.liveCaptionEnabled}
        role="switch"
        aria-checked={recordingStore.liveCaptionEnabled}
        aria-label="ライブ字幕"
        onclick={toggleLive}
      >
        <i></i>
      </button>
    </div>
  {/if}
</div>

<style>
  .recstrip {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: 10px 12px;
    border-bottom: 1px solid var(--color-border);
    background: var(--color-bg);
  }
  .recrow {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: 12px;
  }
  .live-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--color-fg);
    font-weight: 500;
  }
  .hint {
    margin-left: auto;
    font-size: 11px;
    color: var(--color-fg-muted);
  }
  .recnow {
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: 12px;
    color: var(--color-error);
    font-weight: 600;
  }
  .rectimer {
    margin-left: 6px;
    font-family: var(--font-mono);
    font-size: 15px;
    font-weight: 600;
  }
  .stopbtn {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    border: 1px solid var(--color-error);
    background: var(--color-error);
    color: #fff;
    border-radius: 7px;
    padding: 3px 9px;
    font-size: 12px;
    font-weight: 600;
  }
  .switch {
    width: 38px;
    height: 22px;
    border-radius: 999px;
    background: var(--color-accent);
    position: relative;
    flex: none;
    border: none;
    padding: 0;
  }
  .switch.off {
    background: #c8c8cd;
  }
  .switch i {
    position: absolute;
    top: 2px;
    width: 18px;
    height: 18px;
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
  .minimeters {
    display: grid;
    grid-template-columns: auto 1fr auto 1fr;
    gap: 5px 7px;
    align-items: center;
    font-size: 10px;
    color: var(--color-fg-muted);
  }
  .mini {
    height: 6px;
    background: #e4e4e8;
    border-radius: 999px;
    overflow: hidden;
  }
  .mini i {
    display: block;
    height: 100%;
    background: linear-gradient(90deg, var(--color-success), var(--color-warning));
    border-radius: 999px;
    transition: width 0.1s linear;
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    display: inline-block;
  }
  .pulse {
    background: var(--color-error);
    animation: pulse 1.1s infinite;
  }
  @keyframes pulse {
    0% {
      opacity: 1;
    }
    50% {
      opacity: 0.25;
    }
    100% {
      opacity: 1;
    }
  }
</style>

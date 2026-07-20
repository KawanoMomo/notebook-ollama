<script lang="ts">
  import { Square, Mic, MicOff, Volume2, VolumeX } from '@lucide/svelte';
  import { recordingStore } from '$lib/stores/recording.svelte';
  import { presentationStore } from '$lib/stores/presentation.svelte';
  import { pushToast } from './Toast.svelte';
  import Spinner from './Spinner.svelte';
  import Modal from './Modal.svelte';
  import Button from './Button.svelte';

  interface Props {
    // Accepted for symmetry with SourcesPanel and future per-notebook gain
    // controls; the recording lifecycle itself is owned by recordingStore.
    notebookId: string;
  }
  let {}: Props = $props();

  // 発表モード中(presentationStore.active)は「停止」を「発表を終了」に読み替え、
  // 即 stop() せず確認 Modal を挟む(誤タップで発表を止めてしまう事故を防ぐ)。
  // 通常録音時(active=false)は従来どおり即 stop() で挙動不変。
  let showEndConfirm = $state(false);

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

  function onStopClick() {
    if (presentationStore.active) {
      // 発表中は誤操作防止のため確認 Modal を挟む。ここでは stop しない。
      showEndConfirm = true;
      return;
    }
    void stop();
  }

  async function confirmEndPresentation() {
    showEndConfirm = false;
    try {
      // presentationStore.end() が内部で recordingStore.stop() を呼ぶ(録音停止
      // +ソース化)。ここで stop() を重ねて呼ぶと二重停止になるため呼ばない。
      await presentationStore.end();
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
      <button class="stopbtn" onclick={onStopClick} disabled={recordingStore.stopping}>
        {#if recordingStore.stopping}
          <Spinner size={12} /> 停止中…
        {:else}
          <Square size="12" fill="currentColor" /> {presentationStore.active ? '発表を終了' : '停止'}
        {/if}
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
      <button
        class="muteicon"
        class:on={recordingStore.micMuted}
        aria-pressed={recordingStore.micMuted}
        aria-label={recordingStore.micMuted ? 'マイクのミュートを解除' : 'マイクをミュート'}
        title={recordingStore.micMuted ? 'マイクのミュートを解除' : 'マイクをミュート'}
        onclick={() => recordingStore.toggleMute('mic')}
      >
        {#if recordingStore.micMuted}<MicOff size="14" />{:else}<Mic size="14" />{/if}
      </button>
      <div class="mini" class:muted={recordingStore.micMuted}>
        <i style="width:{recordingStore.micMuted ? 0 : Math.round(recordingStore.micLevel * 100)}%"></i>
      </div>
      <button
        class="muteicon"
        class:on={recordingStore.systemMuted}
        aria-pressed={recordingStore.systemMuted}
        aria-label={recordingStore.systemMuted ? 'システム音のミュートを解除' : 'システム音をミュート'}
        title={recordingStore.systemMuted ? 'システム音のミュートを解除' : 'システム音をミュート'}
        onclick={() => recordingStore.toggleMute('system')}
      >
        {#if recordingStore.systemMuted}<VolumeX size="14" />{:else}<Volume2 size="14" />{/if}
      </button>
      <div class="mini" class:muted={recordingStore.systemMuted}>
        <i style="width:{recordingStore.systemMuted ? 0 : Math.round(recordingStore.sysLevel * 100)}%"></i>
      </div>
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

{#if showEndConfirm}
  <Modal title="発表を終了しますか？" onClose={() => (showEndConfirm = false)}>
    <p class="confirm-body">録音を停止してソース化します</p>
    <div class="confirm-actions">
      <Button variant="secondary" onclick={() => (showEndConfirm = false)}>キャンセル</Button>
      <Button variant="danger" onclick={confirmEndPresentation}>終了する</Button>
    </div>
  </Modal>
{/if}

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
  .stopbtn:disabled {
    opacity: 0.6;
    cursor: default;
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
  /* マイク/システムを横並び1行に: [🎤ボタン][メータ][🔊ボタン][メータ] */
  .minimeters {
    display: grid;
    grid-template-columns: auto 1fr auto 1fr;
    gap: 5px 7px;
    align-items: center;
    font-size: 10px;
    color: var(--color-fg-muted);
  }
  /* 左のアイコン自体がミュートトグル(別ボタンを増やさない) */
  .muteicon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border-radius: 6px;
    border: none;
    background: transparent;
    color: var(--color-fg-muted);
    cursor: pointer;
    padding: 0;
    flex: none;
  }
  .muteicon:hover {
    background: var(--color-bg-elevated);
    color: var(--color-fg);
  }
  .muteicon.on {
    background: var(--color-error);
    color: #fff;
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
  /* ミュート中: 該当メータをグレーアウト */
  .mini.muted {
    opacity: 0.5;
  }
  .mini.muted i {
    background: #c8c8cd;
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
  .confirm-body {
    margin: 0;
    font-size: 13px;
    color: var(--color-fg);
  }
  .confirm-actions {
    display: flex;
    gap: var(--space-2);
    justify-content: flex-end;
    margin-top: var(--space-4);
  }
</style>

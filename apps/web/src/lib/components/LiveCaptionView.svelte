<script lang="ts">
  import { tick } from 'svelte';
  import { recordingStore } from '$lib/stores/recording.svelte';

  let bodyEl = $state<HTMLDivElement | null>(null);

  function fmtTime(ms: number): string {
    const total = Math.floor(ms / 1000);
    const m = Math.floor(total / 60)
      .toString()
      .padStart(2, '0');
    const s = (total % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  }

  function isYou(label: string): boolean {
    return label === 'あなた';
  }

  // 新しい字幕が来たら最下部へ自動スクロール
  $effect(() => {
    // captions の長さ変化を購読
    void recordingStore.captions.length;
    void tick().then(() => {
      if (bodyEl) bodyEl.scrollTop = bodyEl.scrollHeight;
    });
  });
</script>

<div class="live">
  <div class="live-head">
    <span class="lh-t"><span class="dot pulse"></span> ライブ字幕</span>
    <span class="lh-note">プレビュー専用 — RAGソースは停止後に高精度生成</span>
  </div>
  <div class="live-body" bind:this={bodyEl}>
    {#each recordingStore.captions as cap (cap.id)}
      <div class="capline" class:interim={!cap.is_final}>
        <span class="t">{fmtTime(cap.start_ms)}</span>
        <span
          class="spk-chip"
          class:you={isYou(cap.label)}
          class:them={!isYou(cap.label)}
        >
          {isYou(cap.label) ? 'あなた' : '相手'}
        </span>
        <span class="ctext">{cap.text}</span>
      </div>
    {/each}
    {#if recordingStore.captions.length === 0}
      <p class="empty">
        {recordingStore.liveCaptionActive
          ? '音声を待っています…'
          : 'ライブ字幕は無効です。録音は継続中です。'}
      </p>
    {/if}
  </div>
  <div class="live-foot">
    {#if recordingStore.error}
      <span class="dot err"></span>
      <span class="errmsg">{recordingStore.error}</span>
    {:else}
      <span class="dot ok"></span>
      文字起こし中(faster-whisper)・話者は「あなた / 相手」の2値表示
    {/if}
  </div>
</div>

<style>
  .live {
    display: flex;
    flex-direction: column;
    height: 100%;
    background: var(--color-bg);
  }
  .live-head {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 20px;
    border-bottom: 1px solid var(--color-border);
    background: var(--color-bg-elevated);
  }
  .lh-t {
    font-size: 14px;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .lh-note {
    margin-left: auto;
    font-size: 11px;
    color: var(--color-fg-muted);
  }
  .live-body {
    flex: 1;
    overflow-y: auto;
    padding: 18px 22px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    min-height: 0;
  }
  .capline {
    display: flex;
    gap: 10px;
    align-items: flex-start;
    font-size: 14px;
    line-height: 1.6;
  }
  .capline .t {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--color-fg-muted);
    padding-top: 4px;
    flex: none;
    width: 38px;
  }
  .capline.interim {
    opacity: 0.55;
    font-style: italic;
  }
  .ctext {
    word-break: break-word;
  }
  .spk-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 11px;
    font-weight: 600;
    border-radius: 999px;
    padding: 2px 9px;
    color: #fff;
    flex: none;
  }
  .spk-chip.you {
    background: var(--color-accent);
  }
  .spk-chip.them {
    background: #16a34a;
  }
  .empty {
    color: var(--color-fg-muted);
    font-size: 13px;
    text-align: center;
    margin-top: var(--space-6);
  }
  .live-foot {
    padding: 9px 20px;
    border-top: 1px solid var(--color-border);
    background: var(--color-bg-elevated);
    font-size: 11px;
    color: var(--color-fg-muted);
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .errmsg {
    color: var(--color-error);
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    display: inline-block;
    flex: none;
  }
  .dot.ok {
    background: var(--color-success);
  }
  .dot.err {
    background: var(--color-error);
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

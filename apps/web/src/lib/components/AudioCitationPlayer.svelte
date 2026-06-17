<script lang="ts">
  interface Props {
    notebookId: string;
    sourceId: string;
    startMs: number;
    endMs: number | null;
    speaker: string | null;
  }
  let { notebookId, sourceId, startMs, endMs, speaker }: Props = $props();

  // mic = "あなた" (self / microphone), otherwise the system/loopback channel.
  let channel = $derived(speaker === 'あなた' ? 'mic' : 'system');
  let src = $derived(
    `/api/notebooks/${notebookId}/sources/${sourceId}/audio?channel=${channel}`,
  );

  // Speaker chip colour: self → accent blue, others → green.
  let chipColor = $derived(speaker === 'あなた' ? 'var(--color-accent)' : '#16a34a');
  let speakerLabel = $derived(speaker ?? '不明');

  let audioEl = $state<HTMLAudioElement | null>(null);
  let playing = $state(false);
  let currentTime = $state(0);
  let duration = $state(0);
  let metadataLoaded = $state(false);
  // True only while playing the bounded excerpt (so we stop at endMs).
  let excerptMode = $state(false);

  function formatTime(seconds: number): string {
    if (!Number.isFinite(seconds) || seconds < 0) return '00:00';
    const total = Math.floor(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  function seekToStart() {
    if (!audioEl) return;
    audioEl.currentTime = startMs / 1000;
    currentTime = audioEl.currentTime;
  }

  // React to a new excerpt (chunk/source change). Re-seek once metadata is ready;
  // the audio element silently clamps currentTime until it can honour the seek.
  $effect(() => {
    // track the inputs that define "a new excerpt"
    void startMs;
    void src;
    if (!audioEl) return;
    excerptMode = false;
    if (metadataLoaded) {
      seekToStart();
    }
  });

  function onLoadedMetadata() {
    if (!audioEl) return;
    metadataLoaded = true;
    duration = audioEl.duration;
    // Position the head at the excerpt start as soon as we can seek.
    seekToStart();
  }

  function onTimeUpdate() {
    if (!audioEl) return;
    currentTime = audioEl.currentTime;
    if (excerptMode && endMs != null && currentTime * 1000 >= endMs) {
      audioEl.pause();
      excerptMode = false;
    }
  }

  function onPlay() {
    playing = true;
  }
  function onPause() {
    playing = false;
  }
  function onEnded() {
    playing = false;
    excerptMode = false;
  }

  function togglePlay() {
    if (!audioEl) return;
    if (audioEl.paused) {
      // free playback from current position — not bounded by endMs
      excerptMode = false;
      void audioEl.play();
    } else {
      audioEl.pause();
    }
  }

  function playExcerpt() {
    if (!audioEl) return;
    seekToStart();
    excerptMode = true;
    void audioEl.play();
  }

  function onSeek(e: Event) {
    if (!audioEl) return;
    const value = Number((e.currentTarget as HTMLInputElement).value);
    audioEl.currentTime = value;
    currentTime = value;
    // manual scrub exits the bounded excerpt
    excerptMode = false;
  }
</script>

<div class="player">
  <audio
    bind:this={audioEl}
    {src}
    preload="metadata"
    onloadedmetadata={onLoadedMetadata}
    ontimeupdate={onTimeUpdate}
    onplay={onPlay}
    onpause={onPause}
    onended={onEnded}
  ></audio>

  <div class="row1">
    <button
      class="play"
      type="button"
      onclick={togglePlay}
      aria-label={playing ? '一時停止' : '再生'}
    >
      {playing ? '⏸' : '▶'}
    </button>
    <input
      class="track"
      type="range"
      min="0"
      max={duration || 0}
      step="0.01"
      value={currentTime}
      oninput={onSeek}
      aria-label="シーク"
    />
  </div>

  <div class="row2">
    <span class="spk-chip" style="background:{chipColor}">● {speakerLabel}</span>
    <span class="ttime">{formatTime(currentTime)} / {formatTime(duration)}</span>
  </div>

  <button class="seg-jump" type="button" onclick={playExcerpt}>
    ↻ この箇所を再生
    {#if endMs != null}
      <span class="span">({formatTime(startMs / 1000)}〜{formatTime(endMs / 1000)})</span>
    {:else}
      <span class="span">({formatTime(startMs / 1000)}〜)</span>
    {/if}
  </button>
</div>

<style>
  .player {
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-3);
    background: var(--color-bg);
    margin-bottom: var(--space-3);
  }
  .row1 {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }
  .play {
    width: 34px;
    height: 34px;
    border-radius: 50%;
    border: none;
    background: var(--color-accent);
    color: #fff;
    display: grid;
    place-items: center;
    flex: none;
    font-size: 13px;
    line-height: 1;
  }
  .play:hover {
    background: var(--color-accent-hover);
  }
  .track {
    flex: 1;
    min-width: 0;
    height: 6px;
    accent-color: var(--color-accent);
    cursor: pointer;
  }
  .row2 {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: var(--space-2);
  }
  .spk-chip {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    font-size: 11px;
    font-weight: 600;
    border-radius: 999px;
    padding: 2px 9px;
    color: #fff;
  }
  .ttime {
    font-size: 11px;
    color: var(--color-fg-muted);
    font-family: var(--font-mono);
  }
  .seg-jump {
    display: flex;
    align-items: center;
    gap: var(--space-1);
    font-size: 11px;
    color: var(--color-accent);
    background: none;
    border: none;
    padding: 0;
    margin-top: var(--space-2);
  }
  .seg-jump:hover {
    text-decoration: underline;
  }
  .seg-jump .span {
    font-family: var(--font-mono);
    color: var(--color-fg-muted);
  }
</style>

<script lang="ts">
  interface Props {
    notebookId: string;
    sourceId: string;
    channel: 'mic' | 'system';
    // Bindable ref so the parent transcript can drive seeks on line-click.
    seek?: (ms: number) => void;
  }
  let { notebookId, sourceId, channel, seek = $bindable() }: Props = $props();

  let src = $derived(
    `/api/notebooks/${notebookId}/sources/${sourceId}/audio?channel=${channel}`,
  );

  let audioEl = $state<HTMLAudioElement | null>(null);
  let playing = $state(false);
  let currentTime = $state(0);
  let duration = $state(0);
  let metadataLoaded = $state(false);

  function formatTime(seconds: number): string {
    if (!Number.isFinite(seconds) || seconds < 0) return '00:00';
    const total = Math.floor(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  // Publish the seek handler to the parent. Seeking does not auto-play; if
  // already playing, the head moves and playback continues from there.
  seek = (ms: number) => {
    if (!audioEl) return;
    if (!metadataLoaded) {
      // metadata not ready yet: defer one tick by setting then re-applying
      audioEl.currentTime = ms / 1000;
      return;
    }
    audioEl.currentTime = ms / 1000;
    currentTime = audioEl.currentTime;
    if (audioEl.paused) {
      void audioEl.play();
    }
  };

  function onLoadedMetadata() {
    if (!audioEl) return;
    metadataLoaded = true;
    duration = audioEl.duration;
  }
  function onTimeUpdate() {
    if (!audioEl) return;
    currentTime = audioEl.currentTime;
  }
  function onPlay() {
    playing = true;
  }
  function onPause() {
    playing = false;
  }
  function onEnded() {
    playing = false;
  }

  function togglePlay() {
    if (!audioEl) return;
    if (audioEl.paused) {
      void audioEl.play();
    } else {
      audioEl.pause();
    }
  }

  function onSeek(e: Event) {
    if (!audioEl) return;
    const value = Number((e.currentTarget as HTMLInputElement).value);
    audioEl.currentTime = value;
    currentTime = value;
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
    <span class="ttime">{formatTime(currentTime)} / {formatTime(duration)}</span>
  </div>
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
  .ttime {
    font-size: 11px;
    color: var(--color-fg-muted);
    font-family: var(--font-mono);
    flex: none;
  }
</style>

<script lang="ts">
  interface Props {
    notebookId: string;
    sourceId: string;
    startMs: number;
    endMs: number | null;
    speaker: string | null;
    // 任意: 渡されたときだけ話者チップをクリック編集可能にする(後方互換)。
    // (fromLabel, toLabel) を親に通知し、親が API 呼び出し + 表示更新を担う。
    onRenameSpeaker?: (fromLabel: string, toLabel: string) => void;
  }
  let { notebookId, sourceId, startMs, endMs, speaker, onRenameSpeaker }: Props = $props();

  // mic = "あなた" (self / microphone), otherwise the system/loopback channel.
  let channel = $derived(speaker === 'あなた' ? 'mic' : 'system');
  let src = $derived(
    `/api/notebooks/${notebookId}/sources/${sourceId}/audio?channel=${channel}`,
  );

  // Speaker chip colour: self → accent blue, others → green.
  let chipColor = $derived(speaker === 'あなた' ? 'var(--color-accent)' : '#16a34a');
  let speakerLabel = $derived(speaker ?? '不明');

  // 話者チップのインライン編集 (SourceCard パターン流用)。
  // onRenameSpeaker が渡されたときのみ編集可。Enter/✓ で確定、Esc/✕ で取消。
  // 確定値が空 or 変更なしなら親へ通知しない (no-op)。
  let editingSpeaker = $state(false);
  let speakerEditValue = $state('');

  function startSpeakerEdit() {
    if (!onRenameSpeaker) return;
    speakerEditValue = speaker ?? '';
    editingSpeaker = true;
  }

  function commitSpeakerEdit() {
    if (!editingSpeaker) return;
    editingSpeaker = false;
    const next = speakerEditValue.trim();
    const from = speaker ?? '';
    if (!next || next === from || !from) return;
    onRenameSpeaker?.(from, next);
  }

  function cancelSpeakerEdit() {
    editingSpeaker = false;
  }

  function onSpeakerEditKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault();
      commitSpeakerEdit();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cancelSpeakerEdit();
    }
  }

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
    {#if editingSpeaker}
      <span class="spk-edit">
        <span class="dot" style="background:{chipColor}"></span>
        <!-- svelte-ignore a11y_autofocus -->
        <input
          class="spk-input"
          type="text"
          bind:value={speakerEditValue}
          onkeydown={onSpeakerEditKeydown}
          autofocus
          aria-label="話者名を編集"
        />
        <button
          class="spk-act ok"
          type="button"
          onclick={commitSpeakerEdit}
          aria-label="確定"
          title="確定">✓</button
        >
        <button
          class="spk-act cancel"
          type="button"
          onclick={cancelSpeakerEdit}
          aria-label="取消"
          title="取消">✕</button
        >
      </span>
    {:else if onRenameSpeaker}
      <button
        class="spk-chip editable"
        type="button"
        style="background:{chipColor}"
        onclick={startSpeakerEdit}
        aria-label="話者名を編集"
        title="クリックで話者名を編集">● {speakerLabel}</button
      >
    {:else}
      <span class="spk-chip" style="background:{chipColor}">● {speakerLabel}</span>
    {/if}
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
  /* クリック編集可の chip は button だが見た目は span と同一にする。 */
  button.spk-chip {
    border: none;
    cursor: pointer;
    font: inherit;
    font-size: 11px;
    font-weight: 600;
    line-height: 1.2;
  }
  button.spk-chip.editable:hover {
    filter: brightness(1.08);
  }
  .spk-edit {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
  }
  .spk-edit .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex: none;
  }
  .spk-input {
    width: 9em;
    min-width: 0;
    font-size: 11px;
    font-weight: 600;
    border: 1px solid var(--color-accent);
    border-radius: var(--radius-sm);
    padding: 1px var(--space-1);
  }
  .spk-act {
    border: none;
    background: none;
    padding: 0 2px;
    font-size: 12px;
    line-height: 1;
    cursor: pointer;
  }
  .spk-act.ok {
    color: var(--color-success);
  }
  .spk-act.cancel {
    color: var(--color-fg-muted);
  }
  .spk-act:hover {
    filter: brightness(0.85);
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

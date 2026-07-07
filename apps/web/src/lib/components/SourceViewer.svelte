<script lang="ts">
  import {
    sourceDetailApi,
    type ChunkDetail,
    type SourceContent,
    type RecordingSegmentContent,
  } from '$lib/api/source_outline';
  import { linksApi } from '$lib/api/links';
  import type { SlideUtterancePage } from '$lib/api/types';
  import { currentNotebookStore } from '$lib/stores/currentNotebook.svelte';
  import { conversationStore } from '$lib/stores/conversation.svelte';
  import Spinner from './Spinner.svelte';
  import AudioCitationPlayer from './AudioCitationPlayer.svelte';
  import SharedAudioPlayer from './SharedAudioPlayer.svelte';
  import SlideView from './SlideView.svelte';
  import SpeakerChip from './SpeakerChip.svelte';
  import { pushToast } from './Toast.svelte';
  import { formatBytes } from '$lib/utils/format';

  function formatTimecode(ms: number): string {
    const total = Math.floor(ms / 1000);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  interface Props {
    notebookId: string;
    selectedChunkId: string | null;
    selectedSourceId: string | null;
  }
  let { notebookId, selectedChunkId, selectedSourceId }: Props = $props();

  let chunk = $state<ChunkDetail | null>(null);
  let loading = $state(false);
  let error = $state<string | null>(null);
  let content = $state<SourceContent | null>(null);
  let contentLoading = $state(false);
  let contentError = $state<string | null>(null);
  // Bindable seek handlers published by the per-channel shared players.
  let seekMic = $state<((ms: number) => void) | undefined>(undefined);
  let seekSystem = $state<((ms: number) => void) | undefined>(undefined);
  // 録音チャンク側: 親スライドの該当ページ表示トグル(チャンクテキストと排他表示)。
  let showParentSlide = $state(false);
  // スライド資料側: ページ別発言の逆引き(kind∈{pdf,pptx} の全文表示時のみ取得)。
  let slideUtterances = $state<SlideUtterancePage[] | null>(null);
  let activeUtteranceChunkId = $state<string | null>(null);

  // Resolve source for the chunk (look up in latest assistant message's citations)
  let resolvedSourceId = $derived.by(() => {
    if (selectedSourceId) return selectedSourceId;
    if (!selectedChunkId) return null;
    const latest = [...conversationStore.messages]
      .reverse()
      .find((m) => m.role === 'assistant');
    return latest?.citations.find((c) => c.chunk_id === selectedChunkId)?.source_id ?? null;
  });

  $effect(() => {
    const cid = selectedChunkId;
    const sid = resolvedSourceId;
    if (!cid || !sid) {
      chunk = null;
      return;
    }
    showParentSlide = false; // チャンク切替でトグル状態をリセット
    loading = true;
    error = null;
    sourceDetailApi
      .getChunk(notebookId, sid, cid)
      .then((c) => {
        chunk = c;
      })
      .catch((e) => {
        error = e instanceof Error ? e.message : String(e);
      })
      .finally(() => {
        loading = false;
      });
  });

  $effect(() => {
    const cid = selectedChunkId;
    const sid = resolvedSourceId;
    if (cid || !sid) {
      content = null;
      return;
    }
    contentLoading = true;
    contentError = null;
    sourceDetailApi
      .getSourceContent(notebookId, sid)
      .then((c) => {
        content = c;
      })
      .catch((e) => {
        contentError = e instanceof Error ? e.message : String(e);
      })
      .finally(() => {
        contentLoading = false;
      });
  });

  let sourceMeta = $derived(
    resolvedSourceId
      ? currentNotebookStore.sources.find((s) => s.id === resolvedSourceId)
      : null,
  );

  // 録音チャンク側: 表示中ソースの親リンクを currentNotebookStore.links から逆引き(PM-10)。
  let parentLink = $derived.by(() => {
    if (!resolvedSourceId) return null;
    return (
      currentNotebookStore.links.find((l) => l.child_source_id === resolvedSourceId) ?? null
    );
  });
  let parentSource = $derived.by(() => {
    if (!parentLink) return null;
    return currentNotebookStore.sources.find((s) => s.id === parentLink.parent_source_id) ?? null;
  });
  let parentTitle = $derived(parentSource?.title ?? parentSource?.origin ?? '資料');
  let parentSlidesUrl = $derived(
    parentLink
      ? `/api/notebooks/${notebookId}/sources/${parentLink.parent_source_id}/slides`
      : '',
  );

  // スライド資料側: kind∈{pdf,pptx} のときだけページ別発言の逆引きを取得する。
  let isSlideKind = $derived(sourceMeta?.kind === 'pdf' || sourceMeta?.kind === 'pptx');

  $effect(() => {
    const cid = selectedChunkId;
    const sid = resolvedSourceId;
    const slideKind = isSlideKind;
    if (cid || !sid || !slideKind) {
      slideUtterances = null;
      activeUtteranceChunkId = null;
      return;
    }
    linksApi
      .slideUtterances(notebookId, sid)
      .then((groups) => {
        slideUtterances = groups;
      })
      .catch(() => {
        // fetch 失敗は静かに非表示(既存表示を壊さない)。
        slideUtterances = null;
      });
  });

  // mic("あなた")はチャンネル identity を兼ねる固定ラベル。色・シーク・音声ファイル
  // 選択がこの文字列に依存するため、リネームは禁止する(下の SpeakerChip で onRename を
  // 渡さない + バックエンドでも拒否)。name_inference も "あなた" を改名対象外にしている。
  const MIC_SPEAKER = 'あなた';

  function segChannel(speaker: string | null): 'mic' | 'system' {
    return speaker === MIC_SPEAKER ? 'mic' : 'system';
  }

  // 話者チップの色: 自分(mic) → accent blue, それ以外 → green。
  // (AudioCitationPlayer の chipColor と同一ロジック。)
  function segColor(speaker: string | null): string {
    return speaker === MIC_SPEAKER ? 'var(--color-accent)' : '#16a34a';
  }

  function seekToSegment(seg: RecordingSegmentContent) {
    if (seg.start_ms == null) return;
    const fn = segChannel(seg.speaker) === 'mic' ? seekMic : seekSystem;
    fn?.(seg.start_ms);
  }

  // 話者チップのクリック編集 → source 内の同一話者を一括リネーム。
  // 成功時: 結果トースト + 表示中チャンク / 全文セグメントの speaker をローカル更新。
  async function handleRenameSpeaker(fromLabel: string, toLabel: string) {
    const sid = resolvedSourceId;
    if (!sid) return;
    try {
      const { updated } = await sourceDetailApi.renameSpeaker(
        notebookId,
        sid,
        fromLabel,
        toLabel,
      );
      // 表示中チャンク(引用プレイヤー)を即時更新。
      if (chunk && chunk.speaker === fromLabel) {
        chunk = { ...chunk, speaker: toLabel };
      }
      // 全文表示中のセグメントも同一話者を更新(source 全体に反映)。
      if (content?.kind === 'recording') {
        content = {
          kind: 'recording',
          segments: content.segments.map((s) =>
            s.speaker === fromLabel ? { ...s, speaker: toLabel } : s,
          ),
        };
      }
      // チャット内に既に描画済みの引用カードの表示も更新(spec §3.2)。
      conversationStore.renameSpeakerInSource(sid, fromLabel, toLabel);
      pushToast(`${updated} 件の発言を「${toLabel}」に更新しました`, 'success');
    } catch (e) {
      pushToast(e instanceof Error ? e.message : String(e), 'error');
    }
  }

  // Which channels actually appear, so we only mount players we need.
  let recordingChannels = $derived.by<Array<'mic' | 'system'>>(() => {
    if (content?.kind !== 'recording') return [];
    const set = new Set<'mic' | 'system'>();
    for (const s of content.segments) set.add(segChannel(s.speaker));
    return [...set];
  });
</script>

<div class="viewer">
  {#if sourceMeta}
    <header>
      <h3>{sourceMeta.title ?? sourceMeta.origin ?? '無題'}</h3>
      <div class="meta">
        <span>{sourceMeta.kind}</span>
        {#if sourceMeta.page_count}<span>{sourceMeta.page_count}p</span>{/if}
        {#if sourceMeta.bytes}<span>{formatBytes(sourceMeta.bytes)}</span>{/if}
      </div>
    </header>
  {:else}
    <p class="empty">ソースまたは引用を選択してください</p>
  {/if}

  {#if loading}
    <div class="state"><Spinner /> 読み込み中…</div>
  {:else if error}
    <div class="state err">エラー: {error}</div>
  {:else if chunk}
    <div class="chunk">
      {#if sourceMeta?.kind === 'recording' && chunk.start_ms != null}
        <AudioCitationPlayer
          notebookId={notebookId}
          sourceId={resolvedSourceId!}
          startMs={chunk.start_ms}
          endMs={chunk.end_ms}
          speaker={chunk.speaker}
          onRenameSpeaker={chunk.speaker === MIC_SPEAKER ? undefined : handleRenameSpeaker}
        />
        <div class="path">
          {#if chunk.speaker}{chunk.speaker} · {/if}{formatTimecode(chunk.start_ms)}{#if chunk.end_ms != null}–{formatTimecode(chunk.end_ms)}{/if}
        </div>
        {#if parentLink && chunk.page}
          <div class="parent-info">
            <span class="parent-label">親: {parentTitle} の p.{chunk.page} で発言</span>
            <button
              type="button"
              class="parent-slide-btn"
              aria-label={`該当スライド(p.${chunk.page})を表示`}
              onclick={() => (showParentSlide = !showParentSlide)}
            >
              該当スライド(p.{chunk.page})を表示
            </button>
          </div>
        {/if}
        {#if showParentSlide && parentLink && chunk.page}
          <div class="parent-slide">
            {#key parentSlidesUrl}
              <SlideView url={parentSlidesUrl} page={chunk.page} />
            {/key}
          </div>
        {:else}
          <pre class="text">{chunk.text}</pre>
        {/if}
      {:else}
        {#if chunk.heading_path}
          <div class="path">{chunk.heading_path}</div>
        {/if}
        {#if chunk.page}
          <div class="page">p.{chunk.page}</div>
        {/if}
        <pre class="text">{chunk.text}</pre>
      {/if}
    </div>
  {:else if selectedChunkId === null && resolvedSourceId}
    {#if contentLoading}
      <div class="state"><Spinner /> 読み込み中…</div>
    {:else if contentError}
      <div class="state err">エラー: {contentError}</div>
    {:else if content?.kind === 'document'}
      <div class="fulltext">
        {#each content.sections as section, i (i)}
          <section class="doc-section">
            {#if section.heading_path}
              <div class="path">{section.heading_path}</div>
            {/if}
            {#if section.page}
              <div class="page">p.{section.page}</div>
            {/if}
            <pre class="text">{section.text}</pre>
          </section>
        {/each}
        {#if isSlideKind && slideUtterances && slideUtterances.length > 0}
          <div class="slide-utterances">
            <h4>このページでの発言</h4>
            {#each slideUtterances as group (group.page)}
              <details>
                <summary>p.{group.page} — {group.items.length}件</summary>
                <ul class="utterance-list">
                  {#each group.items as item (item.chunk_id)}
                    <li>
                      <button
                        type="button"
                        class="utterance"
                        onclick={() =>
                          (activeUtteranceChunkId =
                            activeUtteranceChunkId === item.chunk_id ? null : item.chunk_id)}
                      >
                        {#if item.speaker}<span class="speaker">{item.speaker}</span>{/if}
                        <span class="utt-text">{item.text}</span>
                      </button>
                      {#if activeUtteranceChunkId === item.chunk_id}
                        <AudioCitationPlayer
                          notebookId={notebookId}
                          sourceId={item.child_source_id}
                          startMs={item.start_ms ?? 0}
                          endMs={item.end_ms}
                          speaker={item.speaker}
                        />
                      {/if}
                    </li>
                  {/each}
                </ul>
              </details>
            {/each}
          </div>
        {/if}
      </div>
    {:else if content?.kind === 'recording'}
      <div class="fulltext">
        {#if recordingChannels.includes('mic')}
          <SharedAudioPlayer
            {notebookId}
            sourceId={resolvedSourceId}
            channel="mic"
            bind:seek={seekMic}
          />
        {/if}
        {#if recordingChannels.includes('system')}
          <SharedAudioPlayer
            {notebookId}
            sourceId={resolvedSourceId}
            channel="system"
            bind:seek={seekSystem}
          />
        {/if}
        <ul class="transcript">
          {#each content.segments as seg (seg.ord)}
            <li class="line">
              {#if seg.speaker}
                <SpeakerChip
                  speaker={seg.speaker}
                  color={segColor(seg.speaker)}
                  onRename={seg.speaker === MIC_SPEAKER ? undefined : handleRenameSpeaker}
                />
              {/if}
              <button
                type="button"
                class="seek"
                onclick={() => seekToSegment(seg)}
                disabled={seg.start_ms == null}
              >
                {#if seg.start_ms != null}
                  <span class="tc">{formatTimecode(seg.start_ms)}</span>
                {/if}
                <span class="utt">{seg.text}</span>
              </button>
            </li>
          {/each}
        </ul>
      </div>
    {/if}
  {/if}
</div>

<style>
  .viewer {
    padding: var(--space-3);
    height: 100%;
    overflow-y: auto;
  }
  header h3 {
    margin: 0 0 var(--space-2);
    font-size: 14px;
  }
  .meta {
    display: flex;
    gap: var(--space-2);
    font-size: 12px;
    color: var(--color-fg-muted);
    margin-bottom: var(--space-3);
  }
  .meta span {
    background: var(--color-bg-elevated);
    padding: 1px var(--space-2);
    border-radius: var(--radius-sm);
  }
  .empty,
  .state {
    color: var(--color-fg-muted);
    text-align: center;
    padding: var(--space-5);
    font-size: 13px;
  }
  .err {
    color: var(--color-error);
  }
  .chunk {
    border-top: 1px solid var(--color-border);
    padding-top: var(--space-3);
  }
  .path {
    font-size: 12px;
    color: var(--color-fg-muted);
    margin-bottom: var(--space-1);
  }
  .page {
    font-size: 11px;
    color: var(--color-fg-muted);
    margin-bottom: var(--space-2);
  }
  .parent-info {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    font-size: 12px;
    color: var(--color-fg-muted);
    margin-bottom: var(--space-2);
    flex-wrap: wrap;
  }
  .parent-slide-btn {
    background: none;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    color: var(--color-accent);
    font-size: 12px;
    padding: 2px var(--space-2);
    cursor: pointer;
    flex: none;
  }
  .parent-slide-btn:hover {
    background: var(--color-bg-elevated);
  }
  .parent-slide {
    height: 320px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    overflow: hidden;
    margin-bottom: var(--space-2);
  }
  .text {
    background: var(--color-citation-bg);
    border-left: 3px solid var(--color-citation-border);
    padding: var(--space-3);
    border-radius: var(--radius-sm);
    white-space: pre-wrap;
    font-family: inherit;
    font-size: 13px;
    line-height: 1.6;
    margin: 0;
  }
  .fulltext {
    border-top: 1px solid var(--color-border);
    padding-top: var(--space-3);
  }
  .doc-section {
    margin-bottom: var(--space-3);
  }
  .slide-utterances {
    margin-top: var(--space-3);
    border-top: 1px solid var(--color-border);
    padding-top: var(--space-3);
  }
  .slide-utterances h4 {
    margin: 0 0 var(--space-2);
    font-size: 13px;
    color: var(--color-fg-muted);
  }
  .slide-utterances details {
    margin-bottom: var(--space-2);
  }
  .slide-utterances summary {
    cursor: pointer;
    font-size: 13px;
    padding: var(--space-1) 0;
  }
  .utterance-list {
    list-style: none;
    margin: 0;
    padding: 0 0 0 var(--space-3);
  }
  .utterance-list li {
    margin-bottom: var(--space-1);
  }
  .utterance {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    width: 100%;
    text-align: left;
    background: none;
    border: none;
    padding: var(--space-1);
    cursor: pointer;
    font: inherit;
    color: inherit;
    border-radius: var(--radius-sm);
  }
  .utterance:hover {
    background: var(--color-bg-elevated);
  }
  .utterance .speaker {
    font-size: 11px;
    color: var(--color-fg-muted);
    flex: none;
  }
  .utterance .utt-text {
    font-size: 13px;
    line-height: 1.5;
  }
  .transcript {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .transcript li {
    margin-bottom: var(--space-1);
  }
  .line {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    border-radius: var(--radius-sm);
    padding: var(--space-2);
  }
  .line:hover {
    background: var(--color-bg-elevated);
  }
  .seek {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    flex: 1;
    min-width: 0;
    text-align: left;
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    font: inherit;
    color: inherit;
  }
  .seek:disabled {
    cursor: default;
  }
  .tc {
    font-size: 11px;
    color: var(--color-fg-muted);
    font-family: var(--font-mono);
    flex: none;
  }
  .utt {
    font-size: 13px;
    line-height: 1.6;
  }
</style>

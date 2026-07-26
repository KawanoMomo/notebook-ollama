<script lang="ts">
  import type { Source } from '$lib/api/types';
  import { sourcesApi } from '$lib/api/sources';
  import { FileText, Globe, Mic, CheckCircle, AlertCircle, RefreshCw, Trash2, Pencil, Square, Play, ChevronRight, FileCog, Presentation, Link, Unlink, Table2, Image as ImageIcon, Megaphone } from '@lucide/svelte';
  import Spinner from './Spinner.svelte';
  import RecordingConvStatus from './RecordingConvStatus.svelte';

  interface Props {
    source: Source;
    selected: boolean;
    onToggle: () => void;
    onSelect: () => void;
    onRetry: () => void;
    onReembed: () => void;
    onDelete: () => void;
    // optional にして CR.4 単独でも SourcesPanel の callsite が型エラーにならないようにする
    // (CR.5 で実ハンドラを配線する)。
    onRename?: (id: string, title: string) => void;
    // 進行中の録音変換を停止する(録音 && 変換中のみ表示)。任意。
    onStopConversion?: () => void;
    // ソースガイド(要約)。展開状態は親で制御する(クリックで開閉、選択でも自動展開)。
    guideExpanded?: boolean;
    onGuideToggle?: () => void;
    onSummarize?: () => void;
    // 生成中の要約ジョブを中断する(generating のときのみ表示)。任意。
    onSummaryCancel?: () => void;
    // ADR(Architecture Decision Record)抽出。録音/ドキュメント横断。
    onGenerateAdr?: () => void;
    // 発表モード開始(pdf/pptx のみ)。任意(パネル側が配線しない限りボタンは出さない)。
    onStartPresentation?: () => void;
    // 親子ツリー表示のインデント段数(v1: 0 or 1)。SourcesPanel が
    // orderWithChildren の結果から渡す。カード内部の見た目は不変。
    depth?: number;
    // 親ソースを設定する(全ソース種別で表示、任意配線)。
    onSetParent?: () => void;
    // 親子リンクを解除する(親を持つソースのみ表示するかは呼び出し元の判断=
    // prop を渡すかどうかで制御する)。
    onRemoveParent?: () => void;
    // 表・図の再解析(reingest)。pdf かつ ready/error のときのみ表示(任意配線)。
    onReingest?: () => void;
    // 図の再解析(VLM説明生成)。pdf かつ ready のときのみ表示(任意配線)。
    onDescribeFigures?: () => void;
    // 失敗したソースの不具合報告(error のときのみ表示、任意配線)。
    onReportError?: () => void;
  }
  let {
    source, selected, onToggle, onSelect, onRetry, onReembed, onDelete,
    onRename, onStopConversion,
    guideExpanded = false, onGuideToggle, onSummarize, onSummaryCancel,
    onGenerateAdr, onStartPresentation,
    depth = 0, onSetParent, onRemoveParent, onReingest, onDescribeFigures,
    onReportError,
  }: Props = $props();

  // 要約再生成ボタンの状態(ADR ボタンと同一パターン)。変換未完了の
  // ソースでは確実に失敗するため、無効化してまず変換(再試行)を促す。
  // 図解析フェーズ(ベータ)は status が chunking のまま進むため、SSE 由来の
  // figures_done/figures_total が唯一の進捗表示源になる。完了後は畳む。
  const figureProgress = $derived.by(() => {
    const total = source.figures_total ?? 0;
    const done = source.figures_done ?? 0;
    return total > 0 && done < total ? { done, total } : null;
  });

  const summaryDisabled = $derived(
    (source.chunk_count ?? 0) === 0 ||
      source.status !== 'ready' ||
      source.summary_status === 'generating',
  );
  const summaryButtonLabel = $derived(
    source.summary_status === 'generating'
      ? '要約を生成中…'
      : (source.chunk_count ?? 0) === 0 || source.status !== 'ready'
        ? '変換が完了してから要約できます'
        : '要約を再生成',
  );

  // ADR ボタンの状態(設計: docs/specs/2026-06-26-meeting-adr-templates.md ui_design)
  const adrDisabled = $derived(
    (source.chunk_count ?? 0) === 0 ||
      source.status !== 'ready' ||
      source.adr_status === 'generating',
  );
  const adrButtonLabel = $derived(
    source.adr_status === 'generating'
      ? 'ADR を抽出中…'
      : source.adr_status === 'ready'
        ? 'ADR を再抽出'
        : source.adr_status === 'error'
          ? 'ADR 抽出を再試行'
          : source.adr_status === 'skipped'
            ? 'ADR を再抽出 (Decision 検出なし)'
            : 'ADR を抽出',
  );
  // skipped 時、reason を JSON から取り出して表示する。
  const adrSkipReason = $derived.by(() => {
    if (source.adr_status !== 'skipped' || !source.adr_draft) return null;
    try {
      const o = JSON.parse(source.adr_draft);
      return typeof o?.reason === 'string' ? o.reason : null;
    } catch {
      return null;
    }
  });

  const KIND_ICON: Record<string, typeof FileText> = {
    pdf: FileText,
    markdown: FileText,
    txt: FileText,
    docx: FileText,
    pptx: FileText,
    xlsx: FileText,
    web: Globe,
    recording: Mic,
  };

  function formatDuration(ms: number): string {
    const totalSec = Math.floor(ms / 1000);
    const mm = Math.floor(totalSec / 60);
    const ss = totalSec % 60;
    return `${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`;
  }

  const durationLabel = $derived(
    typeof source.duration_ms === 'number' && source.duration_ms > 0
      ? formatDuration(source.duration_ms)
      : null,
  );

  // Recording sources that are still being converted (not ready / not error) get the
  // detailed step panel rendered below the card body.
  const showConvStatus = $derived(
    source.kind === 'recording' &&
      source.status !== 'ready' &&
      source.status !== 'error',
  );

  // 録音の再生成(再埋め込み)可否: 録音 && 0チャンクで ready && 音源あり。
  // error 録音は既存 retry ボタン(status==='error' で表示)が担い、Step 5 で
  // 録音時のみ recordingRetry へルーティングする。二重ボタンを避けるため
  // canReembed は error を含めず「0チャンク ready」だけを拾う。
  const canReembed = $derived(
    source.kind === 'recording' &&
      (source.chunk_count ?? 0) === 0 &&
      source.status === 'ready' &&
      source.has_audio === true,
  );

  // 発表を開始ボタン(pdf/pptx のみ)。pptx はスライド抽出(has_slides)が
  // 済んでいないと SlideView に描画対象がないため disabled にし、PDF書き出しの
  // 回避策をツールチップでのみ案内する(常時ヒントは出さない)。
  const canPresent = $derived(source.kind === 'pdf' || source.kind === 'pptx');
  const presentationDisabled = $derived(source.kind === 'pptx' && !source.has_slides);
  const presentationTitle = $derived(
    presentationDisabled ? 'PDFに書き出して取り込むと発表できます' : '発表を開始',
  );

  // 録音音声の再生(録音 && 音源あり)。めったに使わない機能なので、再生ボタンで
  // インラインの小さな <audio> を開閉するだけの最小 UI。
  const canPlay = $derived(source.kind === 'recording' && source.has_audio === true);
  let showPlayer = $state(false);
  // ミックス(両チャンネル合成)が主動線。既定選択もミックス。
  let playChannel = $state<'mix' | 'mic' | 'system'>('mix');

  // インライン題名編集。鉛筆クリックで editing=true、Enter/blur で確定、Esc で取消。
  // 確定値が空 or 変更なしなら API を呼ばない (no-op)。
  let editing = $state(false);
  let editValue = $state('');

  const currentTitle = $derived(source.title ?? source.origin ?? '無題');

  function startEdit(e: MouseEvent) {
    e.stopPropagation();
    editValue = source.title ?? '';
    editing = true;
  }

  function commitEdit() {
    if (!editing) return;
    editing = false;
    const next = editValue.trim();
    if (!next || next === (source.title ?? '')) return;
    onRename?.(source.id, next);
  }

  function cancelEdit() {
    editing = false;
  }

  function onEditKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault();
      commitEdit();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cancelEdit();
    }
  }
</script>

<div
  class="card-wrap"
  class:converting={showConvStatus}
  style:margin-left={depth > 0 ? '16px' : undefined}
>
<div class="card" class:err={source.status === 'error'}>
  <input
    type="checkbox"
    checked={selected}
    onchange={onToggle}
    aria-label="このソースをクエリ対象に含める"
  />
  <div class="body-wrap">
    <div class="row">
      {#if (KIND_ICON[source.kind] ?? FileText)}
        {@const Icon = KIND_ICON[source.kind] ?? FileText}
        <Icon size="14" />
      {/if}
      {#if editing}
        <!-- svelte-ignore a11y_autofocus -->
        <input
          class="title-edit"
          type="text"
          bind:value={editValue}
          onkeydown={onEditKeydown}
          onblur={commitEdit}
          onclick={(e) => e.stopPropagation()}
          autofocus
          aria-label="ソース名を編集"
        />
      {:else}
        <button class="title-btn" onclick={onSelect}>
          <span class="title">{currentTitle}</span>
        </button>
        <button
          class="icon edit"
          onclick={startEdit}
          aria-label="名前を編集"
          title="名前を編集"
        >
          <Pencil size="12" />
        </button>
      {/if}
    </div>
    <button class="meta-btn" onclick={onSelect}>
      <div class="meta">
        <span class="kind">{source.kind}</span>
        {#if source.page_count}<span>{source.page_count}p</span>{/if}
        {#if durationLabel}<span>{durationLabel}</span>{/if}
        <span class="status">
          {#if source.status === 'ready'}
            <CheckCircle size="12" color="var(--color-success)" /> ready
          {:else if source.status === 'error'}
            <!-- 本文は meta 行の外に出す。flex 行の中に長文を入れると
                 数文字ずつ折り返されて読めない(実機確認 2026-07-26) -->
            <AlertCircle size="12" color="var(--color-error)" /> エラー
          {:else if source.status === 'embedding' && source.chunk_count}
            <Spinner size={12} /> embedding ({source.embedded ?? 0}/{source.chunk_count})
          {:else if figureProgress}
            <Spinner size={12} /> 図を解析 ({figureProgress.done}/{figureProgress.total})
          {:else}
            <Spinner size={12} /> {source.status}
          {/if}
        </span>
      </div>
    </button>
  </div>
  <div class="actions">
    {#if showConvStatus && onStopConversion}
      <button class="icon" onclick={onStopConversion} aria-label="変換を停止" title="変換を停止">
        <Square size="13" />
      </button>
    {/if}
    {#if source.status === 'error'}
      <button class="icon" onclick={onRetry} aria-label="再試行">
        <RefreshCw size="14" />
      </button>
    {/if}
    {#if source.status === 'error' && onReportError}
      <button
        class="icon"
        onclick={onReportError}
        aria-label="この不具合を報告"
        title="この不具合を報告"
      >
        <Megaphone size="14" />
      </button>
    {/if}
    {#if canReembed}
      <button class="icon" onclick={onReembed} aria-label="再生成" title="再生成">
        <RefreshCw size="14" />
      </button>
    {/if}
    {#if source.kind === 'pdf' && (source.status === 'ready' || source.status === 'error') && onReingest}
      <button class="icon" onclick={onReingest} aria-label="表・図を再解析" title="表・図を再解析">
        <Table2 size="14" />
      </button>
    {/if}
    {#if source.kind === 'pdf' && source.status === 'ready' && onDescribeFigures}
      <button class="icon" onclick={onDescribeFigures} aria-label="図を解析" title="図を解析(VLM説明生成)">
        <ImageIcon size="14" />
      </button>
    {/if}
    {#if canPlay}
      <button
        class="icon"
        class:on={showPlayer}
        onclick={() => (showPlayer = !showPlayer)}
        aria-label="録音を再生"
        title="録音を再生"
      >
        <Play size="14" />
      </button>
    {/if}
    {#if onStartPresentation && canPresent}
      <button
        class="icon"
        onclick={onStartPresentation}
        disabled={presentationDisabled}
        aria-label="発表を開始"
        title={presentationTitle}
      >
        <Presentation size="14" />
      </button>
    {/if}
    {#if onSetParent}
      <button
        class="icon"
        onclick={onSetParent}
        aria-label="親ソースを設定"
        title="親ソースを設定"
      >
        <Link size="14" />
      </button>
    {/if}
    {#if onRemoveParent}
      <button
        class="icon"
        onclick={onRemoveParent}
        aria-label="リンクを解除"
        title="リンクを解除"
      >
        <Unlink size="14" />
      </button>
    {/if}
    <button class="icon danger" onclick={onDelete} aria-label="削除">
      <Trash2 size="14" />
    </button>
  </div>
  {#if source.status === 'error'}
    <!-- カード全幅(グリッド3列ぶん)に置く。body-wrap の中だとアクション列に
         幅を取られ、日本語が数文字ずつ折り返される(実機確認 2026-07-26) -->
    <div class="error-detail">
      <p class="error-msg">{source.error_msg ?? 'error'}</p>
      {#if source.error_remediation}
        <!-- 対処法。message だけでは「何をすれば直るか」が伝わらない
             (実機FB 2026-07-26: 画像PDFの失敗で打つ手が分からなかった) -->
        <p class="remediation">{source.error_remediation}</p>
      {/if}
    </div>
  {/if}
</div>
{#if showConvStatus}
  <RecordingConvStatus sourceId={source.id} />
{/if}
{#if showPlayer && canPlay}
  <div class="player">
    <div class="player-tabs">
      <button class="tab" class:active={playChannel === 'mix'} onclick={() => (playChannel = 'mix')}>
        ミックス
      </button>
      <button class="tab" class:active={playChannel === 'mic'} onclick={() => (playChannel = 'mic')}>
        あなた
      </button>
      <button class="tab" class:active={playChannel === 'system'} onclick={() => (playChannel = 'system')}>
        相手
      </button>
    </div>
    {#key playChannel}
      <!-- svelte-ignore a11y_media_has_caption -->
      <audio
        class="audio"
        controls
        preload="none"
        src={sourcesApi.audioUrl(source.notebook_id, source.id, playChannel)}
      ></audio>
    {/key}
  </div>
{/if}
{#if onGuideToggle}
  <div class="guide">
    <div class="guide-head">
      <button
        class="guide-toggle"
        onclick={onGuideToggle}
        aria-label="ソースガイドを開閉"
      >
        <span class="caret" class:open={guideExpanded}>
          <ChevronRight size="12" />
        </span>
        <span class="guide-title">ソースガイド</span>
      </button>
      {#if onSummarize}
        <button
          class="icon guide-regen"
          onclick={onSummarize}
          disabled={summaryDisabled}
          aria-label={summaryButtonLabel}
          title={summaryButtonLabel}
        >
          <RefreshCw size="12" />
        </button>
      {/if}
      {#if onGenerateAdr}
        <button
          class="icon guide-adr"
          onclick={onGenerateAdr}
          disabled={adrDisabled}
          aria-label={adrButtonLabel}
          title={adrButtonLabel}
        >
          <FileCog size="12" />
          <span class="adr-badge">ADR</span>
        </button>
      {/if}
    </div>
    {#if guideExpanded}
      <div class="guide-body">
        {#if source.summary_status === 'generating'}
          <div class="skeleton">
            <span></span><span></span><span></span>
          </div>
          <p class="guide-hint">
            <Spinner size={12} /> 要約を生成中…
            {#if onSummaryCancel}
              <button
                class="guide-cancel"
                onclick={onSummaryCancel}
                aria-label="要約を中断"
                title="要約を中断"
              >中断</button>
            {/if}
          </p>
        {:else if source.summary_status === 'error'}
          <p class="guide-err">
            <AlertCircle size="12" color="var(--color-error)" />
            生成に失敗しました(3 回)
          </p>
        {:else if source.summary}
          <p class="guide-text">{source.summary}</p>
        {:else}
          <p class="guide-hint">要約はまだ生成されていません</p>
        {/if}

        {#if source.adr_status}
          <div class="adr-section">
            <div class="adr-head">
              <span class="adr-label">ADR</span>
              {#if source.adr_template}
                <span class="adr-meta">{source.adr_template}</span>
              {/if}
              {#if source.adr_confidence}
                <span class="adr-meta conf-{source.adr_confidence}">
                  confidence: {source.adr_confidence}
                </span>
              {/if}
            </div>
            {#if source.adr_status === 'generating'}
              <div class="skeleton">
                <span></span><span></span><span></span><span></span>
              </div>
              <p class="guide-hint"><Spinner size={12} /> ADR を抽出中…</p>
            {:else if source.adr_status === 'error'}
              <p class="guide-err">
                <AlertCircle size="12" color="var(--color-error)" />
                ADR 抽出に失敗しました
              </p>
            {:else if source.adr_status === 'skipped'}
              <p class="guide-hint">
                この資料には Architecture Decision が検出されませんでした
                {#if adrSkipReason}
                  ({adrSkipReason})
                {/if}
              </p>
            {:else if source.adr_status === 'ready' && source.adr_draft}
              <pre class="adr-markdown">{source.adr_draft}</pre>
            {/if}
          </div>
        {/if}
      </div>
    {/if}
  </div>
{/if}
</div>

<style>
  .card-wrap.converting > .card {
    border-bottom: none;
  }
  .card {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border-bottom: 1px solid var(--color-border);
  }
  .card.err {
    background: rgba(211, 47, 47, 0.04);
  }
  .body-wrap {
    min-width: 0;
    overflow: hidden;
  }
  .title-btn,
  .meta-btn {
    background: none;
    border: none;
    text-align: left;
    padding: 0;
    overflow: hidden;
    display: block;
    width: 100%;
    cursor: pointer;
  }
  .title-btn {
    min-width: 0;
    flex: 1;
  }
  .title-edit {
    flex: 1;
    min-width: 0;
    font-size: 13px;
    font-weight: 500;
    border: 1px solid var(--color-accent);
    border-radius: var(--radius-sm);
    padding: 1px var(--space-1);
  }
  .icon.edit {
    opacity: 0;
    flex: none;
  }
  .card:hover .icon.edit {
    opacity: 1;
  }
  .row {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .title {
    font-size: 13px;
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .meta {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: 11px;
    color: var(--color-fg-muted);
    margin-top: var(--space-1);
  }
  .kind {
    background: var(--color-bg-elevated);
    padding: 1px var(--space-2);
    border-radius: var(--radius-sm);
    text-transform: uppercase;
    font-size: 10px;
  }
  .status {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
  }
  .error-detail {
    /* card は grid-template-columns: auto 1fr auto。全列にまたがらせて
       サイドバー幅いっぱいで折り返させる。 */
    grid-column: 1 / -1;
    min-width: 0;
  }
  .error-msg {
    margin: var(--space-1) 0 0;
    font-size: 11px;
    line-height: 1.5;
    color: var(--color-error);
    overflow-wrap: anywhere;
  }
  .remediation {
    margin: 2px 0 0;
    font-size: 11px;
    line-height: 1.5;
    color: var(--color-fg-muted);
    overflow-wrap: anywhere;
  }
  .actions {
    display: flex;
    gap: var(--space-1);
  }
  .icon {
    background: none;
    border: none;
    color: var(--color-fg-muted);
    padding: var(--space-1);
    border-radius: var(--radius-sm);
    display: inline-flex;
  }
  .icon:hover {
    background: var(--color-bg-elevated);
    color: var(--color-fg);
  }
  .icon.danger:hover {
    color: var(--color-error);
  }
  .icon.on {
    background: var(--color-bg-elevated);
    color: var(--color-fg);
  }
  .icon:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }
  .icon:disabled:hover {
    background: none;
    color: var(--color-fg-muted);
  }
  .player {
    padding: var(--space-2) var(--space-3);
    border-bottom: 1px solid var(--color-border);
    background: var(--color-bg-elevated);
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .player-tabs {
    display: flex;
    gap: var(--space-1);
  }
  .tab {
    background: none;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    color: var(--color-fg-muted);
    font-size: 11px;
    padding: 1px var(--space-2);
    cursor: pointer;
  }
  .tab.active {
    border-color: var(--color-accent);
    color: var(--color-fg);
  }
  .audio {
    width: 100%;
    height: 32px;
  }
  .guide {
    border-bottom: 1px solid var(--color-border);
    background: var(--color-bg);
  }
  .guide-head {
    display: flex;
    align-items: center;
    padding: 4px var(--space-3) 4px 28px;
    gap: var(--space-2);
  }
  .guide-toggle {
    flex: 1;
    display: flex;
    align-items: center;
    gap: var(--space-1);
    background: none;
    border: none;
    cursor: pointer;
    padding: 2px 0;
    color: var(--color-fg-muted);
    font-size: 11px;
    text-align: left;
  }
  .guide-toggle:hover {
    color: var(--color-fg);
  }
  .caret {
    display: inline-flex;
    transition: transform 0.15s;
  }
  .caret.open {
    transform: rotate(90deg);
  }
  .guide-title {
    font-weight: 500;
  }
  .guide-regen {
    padding: 2px;
  }
  .guide-body {
    padding: 0 var(--space-3) var(--space-2) 28px;
    font-size: 12px;
    color: var(--color-fg);
  }
  .guide-text {
    margin: 0;
    line-height: 1.55;
  }
  .guide-hint {
    margin: 0;
    color: var(--color-fg-muted);
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
  }
  .guide-cancel {
    border: 1px solid var(--color-border);
    background: transparent;
    color: var(--color-fg-muted);
    border-radius: var(--radius-sm, 4px);
    font-size: inherit;
    padding: 0 var(--space-1);
    cursor: pointer;
  }
  .guide-cancel:hover {
    color: var(--color-error);
    border-color: var(--color-error);
  }
  .guide-err {
    margin: 0;
    color: var(--color-error);
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
  }
  .skeleton {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding-bottom: 4px;
  }
  .skeleton > span {
    height: 8px;
    background: linear-gradient(
      90deg,
      var(--color-bg-elevated) 25%,
      var(--color-border) 50%,
      var(--color-bg-elevated) 75%
    );
    background-size: 200% 100%;
    border-radius: 4px;
    animation: skel 1.4s infinite linear;
  }
  .skeleton > span:nth-child(2) {
    width: 85%;
  }
  .skeleton > span:nth-child(3) {
    width: 65%;
  }
  @keyframes skel {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }
  .guide-adr {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    padding: 2px 4px;
  }
  .guide-adr:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }
  .adr-badge {
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.05em;
    border: 1px solid currentColor;
    border-radius: 3px;
    padding: 0 3px;
    line-height: 1.2;
  }
  .adr-section {
    margin-top: var(--space-3);
    padding-top: var(--space-2);
    border-top: 1px dashed var(--color-border);
  }
  .adr-head {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin-bottom: var(--space-1);
  }
  .adr-label {
    font-size: 11px;
    font-weight: 600;
    color: var(--color-fg);
    letter-spacing: 0.05em;
  }
  .adr-meta {
    font-size: 10px;
    color: var(--color-fg-muted);
    background: var(--color-bg-elevated);
    padding: 1px var(--space-1);
    border-radius: var(--radius-sm);
  }
  .adr-meta.conf-high {
    color: var(--color-success);
  }
  .adr-meta.conf-low {
    color: var(--color-error);
  }
  .adr-markdown {
    margin: 0;
    padding: var(--space-2);
    font-family: var(--font-mono);
    font-size: 11px;
    line-height: 1.55;
    background: var(--color-bg-elevated);
    border-radius: var(--radius-sm);
    max-height: 320px;
    overflow: auto;
    white-space: pre-wrap;
    word-break: break-word;
  }
</style>

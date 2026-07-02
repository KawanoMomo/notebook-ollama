<script lang="ts">
  /**
   * FeedbackTab — 「ご意見・ご要望」タブ (Sprint 8 Task 8.3)
   *
   * spec : docs/specs/2026-06-28-crash-report-feedback-hub-design.md §5.5
   * plan : docs/superpowers/plans/2026-06-28-crash-report-feedback-hub.md Task 8.3
   *
   * 構成 (spec §5.5):
   *   5.5.1 種別チップ (機能要望 / 使いにくさ / 感想) — horizontal toggle group
   *   5.5.2 本文 textarea (kind に応じた placeholder)
   *   5.5.3 Thumbs 3 段階 (Up / Minus = 中立 / Down) — 任意、空でも送信可
   *   5.5.4 スクショ添付 (任意): ファイル選択 + drag&drop + 「現在の画面を自動キャプチャ」
   *   5.5.5 フッタ: 「キャンセル」 / 「送信内容をプレビュー →」
   *
   * 設計判断:
   *
   * - 感情ボタンの "同じものを再クリック" は **toggle off** (= sentiment unset)。
   *   理由: 3 段階のうち 1 つを選んだあと「やっぱり回答しない」に戻したい
   *   ユーザがいる (任意項目なので "未選択" 状態に戻れることが大事)。
   *   別の値をクリックした場合は素直に replace。
   *
   * - 「現在の画面を自動キャプチャ」を押した時 drawer 自身は写り込む方を
   *   採用する。これは spec が ambiguous であるため、parent task instruction
   *   ("default: drawer IS captured") に従った決定。drawer 内に
   *   `.no-screenshot` クラスを付与すれば除外できるが、ユーザの体感としては
   *   「自分が見ていた画面そのもの」が記録されたほうが報告の意図を保ちやすい。
   *
   * - スクショ送信は `screenshot_b64` (data URL の prefix を剥がした bare base64)
   *   として backend に送る。GitHub Issue URL 自体には 8KB 制限があり画像は
   *   埋め込めないので、これは backend に貯めるだけで Issue URL には載らない
   *   (spec §8.3 注意書きと一致)。
   *
   * - `hub` は DI 可能。「キャンセル」で drawer を閉じる挙動をテストできるよう、
   *   default は global singleton `feedbackHubStore`。
   */
  import {
    CheckSquare,
    AlertCircle,
    MessageSquare,
    ThumbsUp,
    ThumbsDown,
    Minus,
    Image as ImageIcon,
    X,
  } from '@lucide/svelte';
  import { feedbackHubApi } from '$lib/api/feedbackHub';
  import { captureCurrentViewAsFile } from '$lib/utils/screenshotCapture';
  import {
    feedbackHubStore as defaultHub,
    type FeedbackHubStore,
  } from '$lib/stores/feedbackHub.svelte';
  import type { FeedbackKind, Sentiment } from '$lib/api/types';

  interface Props {
    hub?: FeedbackHubStore;
  }
  let { hub = defaultHub }: Props = $props();

  // ---- フォーム状態 -------------------------------------------------------
  let kind = $state<FeedbackKind>('feature');
  let body = $state('');
  let sentiment = $state<Sentiment | null>(null);
  let screenshot = $state<File | null>(null);
  /** Object URL for thumbnail preview. Created/revoked together with `screenshot`. */
  let screenshotUrl = $state<string | null>(null);
  let submitting = $state(false);
  let error = $state<string | null>(null);
  let dragOver = $state(false);

  /** Hidden `<input type=file>` — `bind:this` で参照して「選択」ボタンから programmatic click。 */
  let fileInputEl: HTMLInputElement | null = $state(null);

  // ---- 静的データ ---------------------------------------------------------

  const placeholders: Record<FeedbackKind, string> = {
    feature:
      'ノートブック作成時にテンプレートを選べると便利です。会議録音ノート、調査ノート、読書メモなど...',
    complaint:
      '設定画面が見つけにくい・録音タブが小さい・通知が多すぎる、など具体的に教えてください。',
    impression: '使ってみた感想を自由にお書きください。',
  };

  type KindChip = { value: FeedbackKind; label: string; Icon: typeof CheckSquare };
  const chips: KindChip[] = [
    { value: 'feature', label: '機能要望', Icon: CheckSquare },
    { value: 'complaint', label: '使いにくさ', Icon: AlertCircle },
    { value: 'impression', label: '感想', Icon: MessageSquare },
  ];

  type SentimentChip = { value: Sentiment; label: string; Icon: typeof ThumbsUp };
  const sentiments: SentimentChip[] = [
    { value: 'up', label: 'よかった', Icon: ThumbsUp },
    { value: 'neutral', label: 'ふつう', Icon: Minus },
    { value: 'down', label: 'いまいち', Icon: ThumbsDown },
  ];

  // ---- 操作ハンドラ -------------------------------------------------------

  function pickKind(value: FeedbackKind) {
    kind = value;
  }

  /**
   * 感情ボタンのトグル動作:
   * - 同じ値を再クリック → unset (`null` に戻す)
   * - 違う値をクリック → 上書き
   */
  function pickSentiment(value: Sentiment) {
    sentiment = sentiment === value ? null : value;
  }

  function setScreenshot(file: File) {
    if (screenshotUrl) URL.revokeObjectURL(screenshotUrl);
    screenshot = file;
    screenshotUrl = URL.createObjectURL(file);
  }

  function removeScreenshot() {
    if (screenshotUrl) URL.revokeObjectURL(screenshotUrl);
    screenshot = null;
    screenshotUrl = null;
    if (fileInputEl) fileInputEl.value = '';
  }

  function openFilePicker() {
    fileInputEl?.click();
  }

  function handleFileInput(e: Event) {
    const target = e.target as HTMLInputElement;
    const file = target.files?.[0];
    if (file) setScreenshot(file);
  }

  async function handleAutoCapture() {
    error = null;
    try {
      const file = await captureCurrentViewAsFile();
      setScreenshot(file);
    } catch (e) {
      console.error('[FeedbackTab] auto capture failed', e);
      error = 'スクリーンショットの取得に失敗しました';
    }
  }

  function handleDragOver(e: DragEvent) {
    e.preventDefault();
    dragOver = true;
  }

  function handleDragLeave(e: DragEvent) {
    e.preventDefault();
    dragOver = false;
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    dragOver = false;
    const file = e.dataTransfer?.files?.[0];
    if (!file) return;
    // Adversarial-review fix: 以前は非画像ファイルを silently に捨てていたため、
    // ユーザは「ドロップしたのに何も起きない」体験になっていた。スクショ枠は
    // 画像専用 (spec §5.5.4) なので、明確なエラー文言で affordance を伝える。
    if (!file.type.startsWith('image/')) {
      error = '画像ファイルのみ添付できます';
      return;
    }
    error = null;
    setScreenshot(file);
  }

  /**
   * `File` を base64 (data URL の prefix を剥がした bare body) に変換する。
   * FileReader.readAsDataURL を使うのは、大きなスクショで
   * `btoa(String.fromCharCode(...))` の stack overflow を避けるため。
   */
  function fileToBase64(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => {
        const result = reader.result;
        if (typeof result !== 'string') {
          reject(new Error('FileReader produced a non-string result'));
          return;
        }
        const comma = result.indexOf(',');
        resolve(comma === -1 ? result : result.slice(comma + 1));
      };
      reader.onerror = () =>
        reject(reader.error ?? new Error('FileReader failed'));
      reader.readAsDataURL(file);
    });
  }

  function clearForm() {
    kind = 'feature';
    body = '';
    sentiment = null;
    removeScreenshot();
    error = null;
  }

  function handleCancel() {
    clearForm();
    hub.close();
  }

  /**
   * 「送信内容をプレビュー →」 の活性条件:
   * - body が空 / 空白のみ なら不活性
   * - 送信処理進行中も不活性
   */
  const canSubmit = $derived(body.trim().length > 0 && !submitting);

  async function handleSubmit() {
    if (!canSubmit) return;
    submitting = true;
    error = null;
    try {
      let screenshot_b64: string | null = null;
      if (screenshot) {
        screenshot_b64 = await fileToBase64(screenshot);
      }
      const res = await feedbackHubApi.submitFeedback({
        kind,
        body: body.trim(),
        sentiment: sentiment ?? null,
        screenshot_b64,
      });
      // 別タブで GitHub Issue 起票画面を開く。spec §5.7 同様、ユーザが
      // 自分の意志で送信できるように window.open のみで終わる (auto submit は禁止)。
      window.open(res.prefill_url, '_blank');
    } catch (e) {
      console.error('[FeedbackTab] submit failed', e);
      error = e instanceof Error ? e.message : String(e);
    } finally {
      submitting = false;
    }
  }
</script>

<div class="tab-root">
  <!-- 5.5.1 種別チップ
       Adversarial-review fix: 以前は `<fieldset>` + `<button aria-pressed>` で
       toggle-button group として表現していたが、種別は「常に 1 つだけ選択され
       初期値も必ず存在する」=> 正しい ARIA パターンは radiogroup + radio。
       SR 読み上げも「1 of 3」と告知され、トグルではなく択一だと伝わる。 -->
  <div class="chips" role="radiogroup" aria-label="種別" data-testid="kind-chips">
    {#each chips as chip (chip.value)}
      {@const active = kind === chip.value}
      <button
        type="button"
        role="radio"
        class="chip"
        class:active
        aria-checked={active ? 'true' : 'false'}
        data-kind={chip.value}
        onclick={() => pickKind(chip.value)}
      >
        <chip.Icon size={14} />
        <span>{chip.label}</span>
      </button>
    {/each}
  </div>

  <!-- 5.5.2 本文 -->
  <label class="field-label" for="feedback-body">ご意見・ご要望</label>
  <textarea
    id="feedback-body"
    class="body"
    data-testid="feedback-body"
    bind:value={body}
    placeholder={placeholders[kind]}
  ></textarea>

  <!-- 5.5.3 感情 -->
  <div class="sentiment-block">
    <p class="field-label">使ってみた感想</p>
    <div class="sentiments" role="group" aria-label="感想">
      {#each sentiments as s (s.value)}
        {@const active = sentiment === s.value}
        <button
          type="button"
          class="sentiment-btn"
          class:active
          aria-pressed={active ? 'true' : 'false'}
          aria-label={s.label}
          data-sentiment={s.value}
          onclick={() => pickSentiment(s.value)}
        >
          <s.Icon size={18} />
        </button>
      {/each}
    </div>
    <p class="help-text">任意です。回答しなくても送信できます。</p>
  </div>

  <!-- 5.5.4 スクショ添付 -->
  <div class="field-label">スクリーンショットを添付 (任意)</div>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="screenshot-card"
    class:drag-over={dragOver}
    data-testid="screenshot-card"
    ondragover={handleDragOver}
    ondragleave={handleDragLeave}
    ondrop={handleDrop}
  >
    {#if screenshot && screenshotUrl}
      <div class="thumb-row">
        <img class="thumb" src={screenshotUrl} alt="添付スクリーンショット" />
        <div class="thumb-meta">
          <div class="thumb-name">{screenshot.name}</div>
          <button
            type="button"
            class="thumb-remove"
            data-testid="screenshot-remove"
            onclick={removeScreenshot}
          >
            <X size={14} />
            削除
          </button>
        </div>
      </div>
    {:else}
      <div class="screenshot-empty">
        <div class="screenshot-empty-left">
          <ImageIcon size={18} />
          <span>スクリーンショットを追加</span>
        </div>
        <button
          type="button"
          class="btn-secondary"
          data-testid="screenshot-select"
          onclick={openFilePicker}
        >
          選択
        </button>
      </div>
      <p class="help-text">
        ドラッグ&ドロップ、またはクリックで選択。アプリ画面の現在の状態も自動キャプチャできます。
      </p>
      <button
        type="button"
        class="btn-capture"
        data-testid="screenshot-auto"
        onclick={handleAutoCapture}
      >
        現在の画面を自動キャプチャ
      </button>
    {/if}
    <input
      bind:this={fileInputEl}
      type="file"
      accept="image/*"
      class="visually-hidden"
      data-testid="screenshot-input"
      onchange={handleFileInput}
    />
  </div>

  {#if error}
    <p class="error" role="alert">{error}</p>
  {/if}

  <!-- 5.5.5 フッタ -->
  <div class="footer-actions">
    <button
      type="button"
      class="btn-ghost"
      data-testid="feedback-cancel"
      onclick={handleCancel}
    >
      キャンセル
    </button>
    <button
      type="button"
      class="btn-primary"
      data-testid="feedback-submit"
      disabled={!canSubmit}
      onclick={handleSubmit}
    >
      送信内容をプレビュー →
    </button>
  </div>
</div>

<style>
  .tab-root {
    padding: var(--space-4);
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    margin: -1px;
    padding: 0;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    border: 0;
  }

  /* ===== 種別チップ (spec §5.5.1) ===== */
  .chips {
    display: flex;
    gap: 8px;
    border: none;
    padding: 0;
    margin: 0;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    font-size: 13px;
    font-weight: 500;
    color: #4b5563;
    background: #fff;
    border: 1px solid #d1d5db;
    border-radius: 8px;
    cursor: pointer;
  }
  .chip:hover {
    border-color: #9ca3af;
    color: #0b0d12;
  }
  .chip.active {
    background: #0b0d12;
    color: #fff;
    border-color: #0b0d12;
  }

  /* ===== ラベル / ヘルプ文 ===== */
  .field-label {
    font-size: 12px;
    font-weight: 600;
    color: #0b0d12;
    margin: 4px 0 0 0;
  }
  .help-text {
    font-size: 11px;
    color: #6b7280;
    line-height: 1.5;
    margin: 6px 0 0 0;
  }

  /* ===== 本文 textarea (spec §5.5.2) ===== */
  .body {
    min-height: 120px;
    padding: 12px 14px;
    font-size: 14px;
    border-radius: 10px;
    border: 1px solid #d1d5db;
    font-family: inherit;
    resize: vertical;
    color: #0b0d12;
    background: #fff;
  }
  .body:focus {
    outline: none;
    border-color: #0b0d12;
  }

  /* ===== 感情 (spec §5.5.3) ===== */
  .sentiment-block {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .sentiments {
    display: flex;
    gap: 6px;
  }
  .sentiment-btn {
    width: 44px;
    height: 44px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: #fff;
    border: 1px solid #d1d5db;
    border-radius: 10px;
    color: #4b5563;
    cursor: pointer;
  }
  .sentiment-btn:hover {
    border-color: #9ca3af;
    color: #0b0d12;
  }
  .sentiment-btn.active {
    background: #0b0d12;
    border-color: #0b0d12;
    color: #fff;
  }

  /* ===== スクショ添付カード (spec §5.5.4) ===== */
  .screenshot-card {
    padding: 14px;
    border: 1px dashed #d1d5db;
    border-radius: 12px;
    background: #fafafa;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .screenshot-card.drag-over {
    border-color: #0b0d12;
    background: #f3f4f6;
  }
  .screenshot-empty {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
  .screenshot-empty-left {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: #4b5563;
    font-size: 13px;
  }
  .btn-secondary {
    padding: 6px 14px;
    font-size: 13px;
    font-weight: 500;
    color: #0b0d12;
    background: #fff;
    border: 1px solid #d1d5db;
    border-radius: 8px;
    cursor: pointer;
  }
  .btn-secondary:hover {
    background: #f3f4f6;
    border-color: #9ca3af;
  }
  .btn-capture {
    align-self: flex-start;
    padding: 6px 14px;
    font-size: 13px;
    font-weight: 500;
    color: #0b0d12;
    background: #fff;
    border: 1px solid #d1d5db;
    border-radius: 8px;
    cursor: pointer;
  }
  .btn-capture:hover {
    background: #f3f4f6;
    border-color: #9ca3af;
  }
  .thumb-row {
    display: flex;
    gap: 12px;
    align-items: center;
  }
  .thumb {
    width: 80px;
    height: 60px;
    object-fit: cover;
    border-radius: 6px;
    border: 1px solid #e5e7eb;
    background: #fff;
  }
  .thumb-meta {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }
  .thumb-name {
    font-size: 12px;
    color: #0b0d12;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 220px;
  }
  .thumb-remove {
    align-self: flex-start;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 10px;
    font-size: 12px;
    color: #6b7280;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    cursor: pointer;
  }
  .thumb-remove:hover {
    background: #f3f4f6;
    color: #0b0d12;
  }

  /* ===== エラー文言 ===== */
  .error {
    margin: 0;
    color: #ef4444;
    font-size: 12px;
  }

  /* ===== フッタ (spec §5.5.5) ===== */
  .footer-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    padding-top: 16px;
    border-top: 1px solid #e5e7eb;
    margin-top: 4px;
  }
  .btn-ghost {
    padding: 8px 14px;
    font-size: 13px;
    font-weight: 500;
    color: #4b5563;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    cursor: pointer;
  }
  .btn-ghost:hover {
    background: #f3f4f6;
    color: #0b0d12;
  }
  .btn-primary {
    padding: 8px 14px;
    font-size: 13px;
    font-weight: 600;
    color: #fff;
    background: #0b0d12;
    border: 1px solid #0b0d12;
    border-radius: 8px;
    cursor: pointer;
  }
  .btn-primary:hover:not(:disabled) {
    background: #1f2937;
  }
  .btn-primary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>

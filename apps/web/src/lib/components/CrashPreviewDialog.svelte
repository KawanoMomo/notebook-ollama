<!--
  CrashPreviewDialog — 大型モーダル (min-width 720px、max-height 92%) で
  クラッシュレポート送信内容を最終確認 / 編集する画面。

  spec: docs/specs/2026-06-28-crash-report-feedback-hub-design.md §5.7
  plan: docs/superpowers/plans/2026-06-28-crash-report-feedback-hub.md Task 5.7

  ## なぜサーバ往復ではなく URL を逆引きしているか

  Sprint 5 MVP では backend `GET /api/crash/{id}/prefill-url` は
  `{url, truncated}` のみを返す (既存契約)。
  本ダイアログは編集可能な `title / body / labels` が必要なので、
  spec §10 の URL ビルダー (`build_issue_url`) と対称な形で:

    1. mount: backend が組み立てた既定 URL を取得 → `URL.searchParams` で
       `title` / `body` / `labels` を逆抽出してフォーム初期値に流す。
    2. 「GitHubで開く →」押下: 編集後フォーム値で URL を再構築
       (`URLSearchParams` は backend の `urlencode(quote_via=quote_plus)` と
       同じ application/x-www-form-urlencoded エンコードなので
       title/body のエンコード結果も一致する) → `window.open(url, '_blank')`。

  サーバ側 `build_issue_url` の 8KB 切詰めロジックは編集後でも有効にすべき
  だが、現状 MVP では「ユーザが編集する量はせいぜい数百 chars」なので
  クライアント側で再ビルドしても URL がしきい値を大きく超えにくい。
  超えた場合の安全弁としてサーバ側に `POST /api/crash/{id}/prefill-url`
  を生やすのは **Sprint 5 follow-up** として plan §Task 5.7 に明記済み。

  ## なぜ markReported が失敗しても window.open は続行するか

  ユーザの主目的は「Issue を起票すること」。markReported は単に
  「次回同じバグでもう一度 prompt しないため」の二次的フラグ。
  - 順序: window.open → markReported (server) → onClose。
  - markReported 失敗時は onClose せずトーストでフィードバック →
    ユーザがリトライ可能。

  ## アクセシビリティ

  - Escape: backdrop の `<svelte:window>` でフック (Modal.svelte と同パターン)。
  - backdrop click も close。
  - ラベル追加 input は Enter で確定 (chip 追加)。
  - 各 chip の削除ボタンは `aria-label="ラベル削除: <name>"`。
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { X } from '@lucide/svelte';
  import Button from './Button.svelte';
  import { pushToast } from './Toast.svelte';
  import { crashApi } from '$lib/api/crash';
  import type { PendingCrash } from '$lib/api/types';

  interface Props {
    crash: PendingCrash;
    onClose: () => void;
    /** Called after a successful dismiss; parent typically reloads the store. */
    onDismissed?: (id: string) => void;
    /** Called after a successful markReported; parent typically reloads the store. */
    onReported?: (id: string) => void;
  }
  let { crash, onClose, onDismissed, onReported }: Props = $props();

  // ----- フォーム状態 (mount 時に backend prefill URL から seed) -----
  let title = $state('');
  let body = $state('');
  let labels = $state<string[]>([]);
  let truncated = $state(false);
  /** backend URL の origin + pathname (issues/new)。再ビルド時に使う。 */
  let baseEndpoint = $state('https://github.com/KawanoMomo/notebook-ollama/issues/new');

  let loading = $state(true);
  let loadError = $state<string | null>(null);
  let dismissing = $state(false);
  let reporting = $state(false);

  let newLabel = $state('');

  onMount(async () => {
    try {
      const res = await crashApi.getPrefillUrl(crash.id);
      const u = new URL(res.url);
      title = u.searchParams.get('title') ?? '';
      body = u.searchParams.get('body') ?? '';
      const rawLabels = u.searchParams.get('labels');
      // 空文字 / null は [] に正規化。"" を split すると [""] になり phantom chip が
      // 出るため必ず Boolean filter で除外する。
      labels = rawLabels ? rawLabels.split(',').filter(Boolean) : [];
      truncated = res.truncated;
      baseEndpoint = `${u.origin}${u.pathname}`;
      loading = false;
    } catch (e) {
      loadError = e instanceof Error ? e.message : String(e);
      loading = false;
    }
  });

  /** spec §10 の build_issue_url と等価な再ビルド (FE 側)。 */
  function rebuildUrl(): string {
    const u = new URL(baseEndpoint);
    u.searchParams.set('title', title);
    u.searchParams.set('body', body);
    u.searchParams.set('labels', labels.join(','));
    return u.toString();
  }

  function addLabel() {
    const trimmed = newLabel.trim();
    if (!trimmed) return;
    if (labels.includes(trimmed)) {
      newLabel = '';
      return;
    }
    labels = [...labels, trimmed];
    newLabel = '';
  }

  function removeLabel(name: string) {
    labels = labels.filter((l) => l !== name);
  }

  async function onDismissClick() {
    if (dismissing) return;
    dismissing = true;
    try {
      await crashApi.dismiss(crash.id);
      onDismissed?.(crash.id);
      onClose();
    } catch (e) {
      pushToast(`却下に失敗しました: ${e instanceof Error ? e.message : String(e)}`, 'error');
    } finally {
      dismissing = false;
    }
  }

  async function onCopyClick() {
    try {
      await navigator.clipboard.writeText(body);
      pushToast('クリップボードにコピーしました', 'success');
    } catch (e) {
      pushToast(
        `コピーに失敗しました: ${e instanceof Error ? e.message : String(e)}`,
        'error',
      );
    }
  }

  async function onOpenGithubClick() {
    if (reporting) return;
    reporting = true;
    // window.open を先に行う:
    // ユーザの直接アクションに紐付けないとブラウザのポップアップブロッカが
    // 抑制する可能性が高い。markReported の成否は副次的なので後段で扱う。
    const url = rebuildUrl();
    window.open(url, '_blank');
    try {
      await crashApi.markReported(crash.id);
      onReported?.(crash.id);
      onClose();
    } catch (e) {
      pushToast(
        `送信状態の記録に失敗しました: ${e instanceof Error ? e.message : String(e)}`,
        'error',
      );
    } finally {
      reporting = false;
    }
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') onClose();
  }

  function onLabelInputKeyDown(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault();
      addLabel();
    }
  }
</script>

<svelte:window onkeydown={onKey} />

<div class="backdrop" onclick={onClose} role="presentation">
  <div
    class="dialog"
    role="dialog"
    aria-modal="true"
    aria-label="クラッシュレポートのプレビュー"
    onclick={(e) => e.stopPropagation()}
  >
    <header>
      <h2>送信内容のプレビュー</h2>
      <button class="close" aria-label="閉じる" onclick={onClose}>
        <X size={18} />
      </button>
    </header>

    <div class="body">
      {#if loading}
        <p class="status">読み込み中...</p>
      {:else if loadError}
        <p class="status error">
          プレビューの読み込みに失敗しました: {loadError}
        </p>
      {:else}
        <label class="field">
          <span class="field-label">タイトル</span>
          <input
            type="text"
            bind:value={title}
            aria-label="タイトル"
            maxlength="256"
          />
        </label>

        <div class="field">
          <span class="field-label">ラベル</span>
          <div class="chips">
            {#each labels as label (label)}
              <span class="chip" data-role="label-chip">
                <span class="chip-text">{label}</span>
                <button
                  type="button"
                  class="chip-remove"
                  aria-label={`ラベル削除: ${label}`}
                  onclick={() => removeLabel(label)}
                >
                  <X size={12} />
                </button>
              </span>
            {/each}
            <input
              type="text"
              class="label-input"
              placeholder="ラベルを追加してEnter"
              aria-label="ラベル追加"
              bind:value={newLabel}
              onkeydown={onLabelInputKeyDown}
            />
          </div>
        </div>

        {#if truncated}
          <p class="warning">
            ⚠ ログが長いため、URL長制限に合わせて末尾が切り詰められています(truncated)。
          </p>
        {/if}

        <label class="field">
          <span class="field-label">本文 (Markdown)</span>
          <textarea
            bind:value={body}
            aria-label="本文"
            spellcheck="false"
          ></textarea>
        </label>
      {/if}
    </div>

    <footer>
      <Button variant="ghost" onclick={onDismissClick} disabled={loading || dismissing}>
        却下
      </Button>
      <div class="footer-right">
        <Button variant="secondary" onclick={onCopyClick} disabled={loading}>
          クリップボードにコピー
        </Button>
        <Button variant="primary" onclick={onOpenGithubClick} disabled={loading || reporting}>
          GitHubで開く →
        </Button>
      </div>
    </footer>
  </div>
</div>

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    justify-content: center;
    align-items: center;
    /* spec §5.7: drawer (z-index ~150) より上に出すため 200 以上 (Toast と並ぶ階層)。 */
    z-index: 250;
  }
  .dialog {
    background: var(--color-bg);
    border-radius: var(--radius-lg);
    min-width: 720px;
    max-width: 92vw;
    max-height: 92vh;
    display: flex;
    flex-direction: column;
    box-shadow: 0 20px 40px rgba(0, 0, 0, 0.25);
  }
  header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--space-3) var(--space-4);
    border-bottom: 1px solid var(--color-border);
  }
  header h2 {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
  }
  .close {
    background: none;
    border: none;
    color: var(--color-fg-muted);
    padding: var(--space-1);
    border-radius: var(--radius-sm);
    cursor: pointer;
  }
  .close:hover {
    background: var(--color-bg-elevated);
  }
  .body {
    padding: var(--space-4);
    overflow: auto;
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .status {
    margin: 0;
    color: var(--color-fg-muted);
    font-size: 13px;
  }
  .status.error {
    color: var(--color-error);
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .field-label {
    font-size: 12px;
    color: var(--color-fg-muted);
  }
  .field input[type='text'],
  .field textarea {
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-2) var(--space-3);
    font-size: 13px;
    font-family: inherit;
    background: var(--color-bg);
    color: var(--color-fg);
  }
  .field textarea {
    /* Markdown 本文用、spec §5.7 の min-height 320px */
    min-height: 320px;
    font-family: ui-monospace, 'Cascadia Code', 'Source Code Pro', monospace;
    line-height: 1.5;
    resize: vertical;
  }
  .field input[type='text']:focus,
  .field textarea:focus,
  .label-input:focus {
    outline: none;
    border-color: var(--color-accent);
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    align-items: center;
    border: 1px dashed var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-2);
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    background: var(--color-bg-elevated);
    color: var(--color-fg);
    border: 1px solid var(--color-border);
    border-radius: 12px;
    padding: 2px 6px 2px 10px;
    font-size: 12px;
  }
  .chip-text {
    line-height: 1.2;
  }
  .chip-remove {
    background: none;
    border: none;
    color: var(--color-fg-muted);
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    padding: 2px;
    border-radius: var(--radius-sm);
  }
  .chip-remove:hover {
    background: var(--color-bg);
    color: var(--color-fg);
  }
  .label-input {
    flex: 1;
    min-width: 160px;
    border: none;
    background: transparent;
    font-size: 12px;
    color: var(--color-fg);
    padding: 2px 4px;
  }
  .warning {
    margin: 0;
    padding: var(--space-2) var(--space-3);
    border-left: 3px solid #f59e0b;
    background: rgba(245, 158, 11, 0.08);
    font-size: 12px;
    color: var(--color-fg);
  }
  footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--space-3) var(--space-4);
    border-top: 1px solid var(--color-border);
  }
  .footer-right {
    display: flex;
    gap: var(--space-2);
  }
</style>

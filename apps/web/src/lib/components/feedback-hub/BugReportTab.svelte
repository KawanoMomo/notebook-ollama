<script lang="ts">
  /**
   * BugReportTab — 不具合タブ (Sprint 7 Task 7.1)。
   *
   * spec: docs/specs/2026-06-28-crash-report-feedback-hub-design.md §5.4
   * plan: docs/superpowers/plans/2026-06-28-crash-report-feedback-hub.md Task 7.1
   *
   * 役割:
   * - 冒頭の説明文 + 「未送信のレポート」リスト + 「+ 新規報告を作成」カード。
   * - 各行から `crashReportsStore.dismiss(id)` / `showPreview(crash)` を発火。
   * - 「+ 新規報告を作成」は空の PendingCrash dict を作って showPreview に渡し、
   *   CrashPreviewDialog を空白フォームで開く (backend は通さない、純フロント完結)。
   *
   * store は DI 可能 (`store` prop)。テストは createCrashReportsStore(mockApi) で
   * 注入し、グローバル singleton の状態漏れを避ける (NoticesTab と同じ流儀)。
   *
   * Sprint 5 lessons: vitest GREEN だけでは Playwright で 5 件の wiring/visual 欠陥
   * が出た。本タブも +layout → Drawer → Tab で正しく結線されているかは
   * 上位の手動視覚ゲートで確認する。
   */
  import { onMount } from 'svelte';
  import { Clock } from '@lucide/svelte';
  import {
    crashReportsStore as defaultStore,
    type CrashReportsStore,
  } from '$lib/stores/crashReports.svelte';
  import type { PendingCrash } from '$lib/api/types';

  interface Props {
    store?: CrashReportsStore;
  }
  let { store = defaultStore }: Props = $props();

  let loading = $state(false);
  let error = $state<string | null>(null);

  async function loadPending() {
    loading = true;
    error = null;
    try {
      await store.load();
    } catch (e) {
      console.error('[BugReportTab] load failed:', e);
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    if (store.pending.length === 0) {
      void loadPending();
    }
  });

  async function handleDismiss(id: string) {
    try {
      await store.dismiss(id);
    } catch (e) {
      // dismiss の失敗はユーザ操作に対する直接フィードバックなので console + 行残し。
      // (toast 派生はここでは出さない: Drawer 内に閉じた挙動にする)
      console.error('[BugReportTab] dismiss failed:', e);
    }
  }

  function handlePreview(crash: PendingCrash) {
    store.showPreview(crash);
  }

  /**
   * 「+ 新規報告を作成」用の空 PendingCrash。
   * - id は `manual-<epoch>` で衝突回避 (同一セッションで連打しても unique)。
   * - source='frontend': backend 由来でないことを明示。
   * - fingerprint='' / trace=[] / hardware={} / log_tail=[] は CrashPreviewDialog 側で
   *   空欄として扱う想定。
   */
  function handleNewManual() {
    const manual: PendingCrash = {
      id: 'manual-' + Date.now(),
      fingerprint: '',
      created_at: new Date().toISOString(),
      exception_type: '',
      exception_message: '',
      trace: [],
      hardware: {},
      log_tail: [],
      source: 'frontend',
    };
    store.showPreview(manual);
  }

  /**
   * trace 配列から「ファイルパス」相当の 1 行目を取り出す。
   * traceback の先頭フレームを使い、無ければ空文字を返す。
   * 表示用 (monospace 11px) なので過剰整形はしない。
   */
  function pickTraceLine(trace: string[]): string {
    return trace[0] ?? '';
  }

  /**
   * `2026-06-28T10:30:00Z` のような ISO-8601 を、ユーザの実時刻
   * (ja-JP locale, ホスト TZ) で整形する。
   *
   * 旧実装は ISO を文字列 slice していたため UTC のまま表示され、
   * JST のユーザに「30 分前のクラッシュが 10 時間前に見える」誤解を生んでいた。
   * 視覚評価フィードバックを受け、Date#toLocaleString に切り替える。
   * パース失敗時は元の文字列をそのまま返す (壊れた ISO で UI を崩さない)。
   */
  function formatDate(iso: string): string {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString('ja-JP');
  }
</script>

<div class="tab-root">
  <p class="description">
    アプリで発生したエラーを開発者に報告できます。送信前にプレビューで内容を確認・編集できます。
  </p>

  {#if loading && store.pending.length === 0}
    <div class="state" role="status" aria-label="読み込み中">
      <div class="spinner" aria-hidden="true"></div>
    </div>
  {:else if error}
    <div class="state error" role="alert">
      <p>クラッシュレポートの取得に失敗しました</p>
      <button type="button" class="retry" onclick={loadPending}>再試行</button>
    </div>
  {:else}
    <!-- 視覚評価フィードバック: heading は #if pending>0 の外に出して常時表示し、
         空状態にも「未送信のレポートはありません」という小さなキャプションを添える。
         こうしておくと「ロード中なのか / 本当に 0 件なのか」が一目で分かる。 -->
    <h3 class="section-heading">未送信のレポート</h3>
    {#if store.pending.length > 0}
      <ul class="crash-list">
        {#each store.pending as crash (crash.id)}
          <li class="crash-row" data-testid="crash-row">
            <div class="crash-main">
              <div class="exception-type">{crash.exception_type}</div>
              {#if crash.exception_message}
                <div class="exception-message">{crash.exception_message}</div>
              {/if}
              {#if pickTraceLine(crash.trace)}
                <div class="file-path">{pickTraceLine(crash.trace)}</div>
              {/if}
              <div class="created-at">{formatDate(crash.created_at)}</div>
            </div>
            <div class="crash-actions">
              <button
                type="button"
                class="action-dismiss"
                data-action="dismiss"
                onclick={() => handleDismiss(crash.id)}
              >
                却下
              </button>
              <button
                type="button"
                class="action-preview"
                data-action="preview"
                onclick={() => handlePreview(crash)}
              >
                プレビュー →
              </button>
            </div>
          </li>
        {/each}
      </ul>
    {:else}
      <p class="empty-notice">未送信のレポートはありません</p>
    {/if}

    <div class="manual-card">
      <div class="manual-icon" aria-hidden="true">
        <Clock size={20} />
      </div>
      <p class="manual-desc">
        手動で新規報告を作成できます。エラーが起きていなくても、気になる挙動を開発者へ伝えられます。
      </p>
      <button type="button" class="manual-btn" onclick={handleNewManual}>
        + 新規報告を作成
      </button>
    </div>
  {/if}
</div>

<style>
  /* spec §5.4 — typography / spacing は固定値で直書き (デザイントークン化は MVP 後) */

  .tab-root {
    padding: var(--space-4);
  }

  /* 冒頭説明文: 13px / #6b7280 / line-height 1.6 (spec §5.4) */
  .description {
    margin: 0 0 24px 0;
    font-size: 13px;
    color: #6b7280;
    line-height: 1.6;
  }

  /* セクション見出し「未送信のレポート」: 11px / 600 / uppercase (spec §5.4) */
  .section-heading {
    margin: 0 0 12px 0;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #6b7280;
  }

  /* 空状態キャプション: section-heading の下に薄く出す (12px / #6b7280) */
  .empty-notice {
    margin: 0 0 24px 0;
    font-size: 12px;
    color: #6b7280;
    line-height: 1.5;
  }

  /* レポートリスト */
  .crash-list {
    list-style: none;
    margin: 0 0 24px 0;
    padding: 0;
  }
  /* 行間 1px solid #e5e7eb (spec §5.4) */
  .crash-row {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    padding: 14px 0;
    border-bottom: 1px solid #e5e7eb;
  }
  .crash-row:last-child {
    border-bottom: none;
  }

  .crash-main {
    flex: 1;
    min-width: 0;
  }
  /* 例外型名: color #ef4444, weight 600 (spec §5.4) */
  .exception-type {
    font-size: 13px;
    font-weight: 600;
    color: #ef4444;
    margin-bottom: 4px;
  }
  /* error 詳細: monospace 11px */
  .exception-message {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 11px;
    color: #0b0d12;
    margin-bottom: 4px;
    word-break: break-all;
  }
  /* ファイルパス: monospace 11px */
  .file-path {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 11px;
    color: #4b5563;
    margin-bottom: 4px;
    word-break: break-all;
  }
  /* 発生日時: color #9ca3af */
  .created-at {
    font-size: 11px;
    color: #9ca3af;
  }

  .crash-actions {
    display: flex;
    flex-direction: column;
    gap: 6px;
    flex-shrink: 0;
  }
  /* 却下ボタン: ghost */
  .action-dismiss {
    background: none;
    border: 1px solid transparent;
    color: #6b7280;
    font-size: 12px;
    padding: 4px 10px;
    border-radius: 6px;
    cursor: pointer;
  }
  .action-dismiss:hover {
    background: #f3f4f6;
    color: #0b0d12;
  }
  /* プレビューボタン: primary */
  .action-preview {
    background: #0b0d12;
    border: 1px solid #0b0d12;
    color: #fff;
    font-size: 12px;
    font-weight: 500;
    padding: 4px 12px;
    border-radius: 6px;
    cursor: pointer;
  }
  .action-preview:hover {
    background: #1f2937;
  }

  /* 「手動で新規報告を作成」カード: dashed border / 12px radius / #fafafa bg (spec §5.4) */
  .manual-card {
    margin-top: 16px;
    padding: 20px 16px;
    border: 1px dashed #d1d5db;
    border-radius: 12px;
    background: #fafafa;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    text-align: center;
  }
  .manual-icon {
    color: #6b7280;
    display: inline-flex;
  }
  .manual-desc {
    margin: 0;
    font-size: 12px;
    color: #6b7280;
    line-height: 1.5;
  }
  .manual-btn {
    background: #fff;
    border: 1px solid #d1d5db;
    color: #0b0d12;
    font-size: 13px;
    font-weight: 500;
    padding: 6px 14px;
    border-radius: 8px;
    cursor: pointer;
  }
  .manual-btn:hover {
    background: #f3f4f6;
    border-color: #9ca3af;
  }

  /* state (loading / empty / error) */
  .state {
    padding: var(--space-6) var(--space-4);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--space-3);
    color: #6b7280;
    font-size: 13px;
  }
  .state p {
    margin: 0;
  }
  .state.error p {
    color: #ef4444;
  }
  .state .retry {
    background: none;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 13px;
    cursor: pointer;
    color: #0b0d12;
  }
  .state .retry:hover {
    background: #f3f4f6;
  }
  .spinner {
    width: 20px;
    height: 20px;
    border: 2px solid #e5e7eb;
    border-top-color: #6b7280;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
</style>

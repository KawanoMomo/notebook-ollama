<script lang="ts">
  /**
   * NoticesTab — お知らせの Linear 風 timeline (Sprint 6 Task 6.2).
   *
   * spec: docs/specs/2026-06-28-crash-report-feedback-hub-design.md §5.3
   * plan: docs/superpowers/plans/2026-06-28-crash-report-feedback-hub.md Task 6.2
   *
   * - 単一カラム縦 timeline (カードグリッドは禁止)。
   * - 日付ヘッダは「2026年6月28日」の和暦表記 (混在禁止)。
   * - 未読マーカーは title 左に直径 6px の `#3b82f6` ドット (::before)。
   * - 色付きバッジは禁止。タイポと spacing で階層を作る。
   * - エントリクリックで `noticesStore.markSeen(id)` → 未読ドット消失 +
   *   header の Megaphone 未読ドット (feedbackHub.unreadCount) も同期して減る。
   *
   * Plan §1625 では mouseenter で markSeen する案だったが、Task 6.2 の指示で
   * 明示性のため click を採用 (キーボード操作は Enter/Space をサポート)。
   *
   * store は DI 可能 (`store` prop)。default は global singleton `noticesStore`。
   * テストは createNoticesStore(mockApi) のインスタンスを渡すことで
   * グローバル singleton への副作用を避ける。
   */
  import { onMount } from 'svelte';
  import { noticesStore as defaultStore, type NoticesStore } from '$lib/stores/notices.svelte';
  import type { Notice } from '$lib/api/types';

  interface Props {
    store?: NoticesStore;
  }
  let { store = defaultStore }: Props = $props();

  let loading = $state(false);
  let error = $state<string | null>(null);

  async function loadNotices() {
    loading = true;
    error = null;
    try {
      await store.load();
    } catch (e) {
      // メッセージはユーザ向けに固定文言。詳細は console に出して開発時に拾えるように。
      console.error('[NoticesTab] load failed:', e);
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    if (store.items.length === 0) {
      void loadNotices();
    }
  });

  /**
   * 日付ごとにグループ化し、日付降順に並べる。
   * 同一日付内のエントリは API が返した順 (= notices.json の配列順) を保つ。
   */
  type DateGroup = { date: string; items: Notice[] };
  const groups = $derived.by<DateGroup[]>(() => {
    const map = new Map<string, Notice[]>();
    for (const n of store.items) {
      const arr = map.get(n.date) ?? [];
      arr.push(n);
      map.set(n.date, arr);
    }
    return Array.from(map.entries())
      .sort(([a], [b]) => (a > b ? -1 : a < b ? 1 : 0))
      .map(([date, items]) => ({ date, items }));
  });

  /**
   * `YYYY-MM-DD` ISO 文字列を「2026年6月28日」に整形する。
   * 月/日はゼロ埋めしない (spec §5.3 の例示と一致)。
   */
  function formatJaDate(iso: string): string {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
    if (!m) return iso;
    const year = parseInt(m[1], 10);
    const month = parseInt(m[2], 10);
    const day = parseInt(m[3], 10);
    return `${year}年${month}月${day}日`;
  }

  function isUnread(id: string): boolean {
    return !store.seenIds.has(id);
  }

  function handleSelect(id: string) {
    store.markSeen(id);
  }

  function handleKey(e: KeyboardEvent, id: string) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      handleSelect(id);
    }
  }
</script>

{#if loading && store.items.length === 0}
  <div class="state" role="status" aria-label="読み込み中">
    <div class="spinner" aria-hidden="true"></div>
  </div>
{:else if error}
  <div class="state error" role="alert">
    <p>お知らせの取得に失敗しました</p>
    <button type="button" class="retry" onclick={loadNotices}>再試行</button>
  </div>
{:else if store.items.length === 0}
  <div class="state empty">
    <p>お知らせはありません</p>
  </div>
{:else}
  <div class="timeline">
    {#each groups as group (group.date)}
      <h3 class="date-header">{formatJaDate(group.date)}</h3>
      {#each group.items as notice (notice.id)}
        <!--
          NoticesTab エントリは Linear と同じく entry 全体を click 対象とする
          (タイトルだけ/小ボタンだけクリッカブルにすると hit-target が痩せる)。
          意図的に noninteractive <article> へ tabindex / handler を載せている。
          キーボードでも Enter/Space で markSeen できる。
        -->
        <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
        <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
        <article
          class="entry"
          class:unread={isUnread(notice.id)}
          tabindex="0"
          onclick={() => handleSelect(notice.id)}
          onkeydown={(e) => handleKey(e, notice.id)}
        >
          <h4 class="entry-title">{notice.title}</h4>
          <p class="entry-body">{notice.body}</p>
          {#if notice.subsections}
            {#each notice.subsections as sub, i (i)}
              <h5 class="subsection-heading">{sub.heading}</h5>
              <ul class="subsection-items">
                {#each sub.items as item, j (j)}
                  <li>{item}</li>
                {/each}
              </ul>
            {/each}
          {/if}
        </article>
      {/each}
    {/each}
  </div>
{/if}

<style>
  /* spec §5.3 — typography / spacing は固定値で直書き (デザイントークン化は MVP 後) */

  .timeline {
    padding: var(--space-4);
  }

  /* 日付ヘッダ: 「2026年6月28日」 — 12px / 500 / uppercase / 0.06em / #6b7280 */
  .date-header {
    font-size: 12px;
    font-weight: 500;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin: 32px 0 16px 0;
    padding-bottom: 8px;
    border-bottom: 1px solid #e5e7eb;
  }
  /* timeline の最上端で 32px の余白がレイアウトを押し下げないように初回だけ詰める */
  .date-header:first-child {
    margin-top: 0;
  }

  .entry {
    margin: 16px 0 32px 0;
    padding: 0;
    cursor: pointer;
    /* outline はキーボードフォーカスのみ表示 (マウスクリックでは出さない) */
    outline: none;
  }
  .entry:focus-visible {
    outline: 2px solid #3b82f6;
    outline-offset: 4px;
    border-radius: 4px;
  }

  /* タイトル: 15px / 600 / -0.01em */
  .entry-title {
    margin: 0 0 8px 0;
    font-size: 15px;
    font-weight: 600;
    letter-spacing: -0.01em;
    color: #0b0d12;
    position: relative;
  }

  /* 未読マーカー: title 左に 6px の青ドット (::before、negative left でテキスト先頭から離す) */
  .entry.unread > .entry-title::before {
    content: '';
    display: inline-block;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #3b82f6;
    margin-right: 8px;
    vertical-align: middle;
    /* baseline 揃えに微調整 */
    transform: translateY(-1px);
  }

  /* 本文: 14px / 400 / 1.65 / #374151 */
  .entry-body {
    margin: 0 0 12px 0;
    font-size: 14px;
    font-weight: 400;
    line-height: 1.65;
    color: #374151;
    white-space: pre-wrap;
  }

  /* サブセクション見出し: 11px / 600 / uppercase / 0.06em / #6b7280 */
  .subsection-heading {
    margin: 12px 0 6px 0;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #6b7280;
  }

  /* 箇条書き: padding-left 18px / line-height 1.7 */
  .subsection-items {
    margin: 0;
    padding-left: 18px;
    line-height: 1.7;
    font-size: 14px;
    color: #374151;
  }
  .subsection-items li {
    margin: 0;
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

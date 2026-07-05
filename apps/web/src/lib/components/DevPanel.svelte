<script lang="ts">
  /**
   * Dev パネル — フローティングオーバーレイ(spec 2026-07-02 §10.2)。
   *
   * stream は 1 本だけ維持し、タブ(=source)は FE 側フィルタ。
   * 下端付近では追従、上へスクロールで追従停止、上端到達で過去を range fetch。
   */
  import { onDestroy, onMount } from 'svelte';
  import { devmode } from '$lib/stores/devmode.svelte';

  interface DevEntry {
    seq: number;
    ts: string;
    level: string;
    source: string;
    msg: string;
    payload: Record<string, unknown>;
  }

  const LS_POS = 'nb-ollama-devpanel-pos';
  const PAGE = 300;
  const MAX_ROWS = 5000; // DOM 保護(サーバ側リングとは独立の表示上限)

  let entries = $state<DevEntry[]>([]);
  let gapAtTop = $state(false);
  let dropNote = $state(0);
  let stats = $state<{ entries: number; bytes: number; dropped_total: number } | null>(null);
  let system = $state<Record<string, unknown> | null>(null);

  let tab = $state<'app' | 'ollama' | 'server' | 'events' | 'system'>('app');
  let levels = $state<Record<string, boolean>>({ debug: true, info: true, warn: true, error: true });
  let search = $state('');
  let follow = $state(true);
  let expanded = $state<Set<number>>(new Set());

  // 位置・サイズ(localStorage 復元)
  function loadBox() {
    const base = { x: 80, y: 80, w: 760, h: 480 };
    try {
      const saved = localStorage.getItem(LS_POS);
      return saved ? { ...base, ...JSON.parse(saved) } : base;
    } catch {
      return base;
    }
  }
  let box = $state(loadBox());
  function persistBox() {
    try {
      localStorage.setItem(LS_POS, JSON.stringify(box));
    } catch {
      /* noop */
    }
  }

  let es: EventSource | null = null;
  let listEl = $state<HTMLDivElement | null>(null);
  let loadingOlder = false;

  const visible = $derived(
    tab === 'system'
      ? []
      : entries.filter(
          (e) =>
            e.source === tab &&
            levels[e.level] !== false &&
            (search.trim() === '' ||
              (e.msg + JSON.stringify(e.payload)).toLowerCase().includes(search.toLowerCase())),
        ),
  );

  function scrollToBottom() {
    if (listEl) listEl.scrollTop = listEl.scrollHeight;
  }

  function pushEntry(e: DevEntry) {
    entries = [...entries.slice(-MAX_ROWS + 1), e];
    if (follow) queueMicrotask(scrollToBottom);
  }

  async function fetchStats() {
    try {
      const r = await fetch('/api/dev/stats');
      if (r.status === 403) return devmode.forceReset();
      if (r.ok) stats = await r.json();
    } catch {
      /* noop */
    }
  }

  async function fetchSystem() {
    try {
      const r = await fetch('/api/dev/system');
      if (r.status === 403) return devmode.forceReset();
      if (r.ok) system = await r.json();
    } catch {
      /* noop */
    }
  }

  async function loadOlder() {
    if (loadingOlder || entries.length === 0) return;
    loadingOlder = true;
    try {
      const first = entries[0].seq;
      const r = await fetch(`/api/dev/range?before_seq=${first}&order=desc&limit=${PAGE}`);
      if (r.status === 403) return devmode.forceReset();
      const data = await r.json();
      const older: DevEntry[] = [...data.entries].reverse();
      if (older.length > 0) {
        const prevHeight = listEl?.scrollHeight ?? 0;
        entries = [...older, ...entries].slice(-MAX_ROWS);
        // スクロール位置を維持(prepend 分だけずらす)
        queueMicrotask(() => {
          if (listEl) listEl.scrollTop = listEl.scrollHeight - prevHeight;
        });
      }
      gapAtTop = Boolean(data.gap_before) || (older.length === 0 && data.oldest_seq < first);
    } catch {
      /* noop */
    } finally {
      loadingOlder = false;
    }
  }

  function onScroll() {
    if (!listEl) return;
    const nearBottom = listEl.scrollHeight - listEl.scrollTop - listEl.clientHeight < 24;
    follow = nearBottom;
    if (listEl.scrollTop < 8) void loadOlder();
  }

  function jumpToLatest() {
    follow = true;
    scrollToBottom();
  }

  async function connect() {
    // 初期バックログ → SSE 追従(since_seq で重複なく接続)
    try {
      const r = await fetch(`/api/dev/range?order=desc&limit=${PAGE}`);
      if (r.status === 403) return devmode.forceReset();
      const data = await r.json();
      entries = [...data.entries].reverse();
      gapAtTop = data.oldest_seq < (entries[0]?.seq ?? data.oldest_seq);
      const last = entries.length > 0 ? entries[entries.length - 1].seq : 0;
      es = new EventSource(`/api/dev/stream?since_seq=${last}`);
      es.addEventListener('entry', (ev) => {
        try {
          pushEntry(JSON.parse((ev as MessageEvent).data));
        } catch {
          /* noop */
        }
      });
      es.addEventListener('gap', () => {
        dropNote += 1;
      });
      es.addEventListener('meta', (ev) => {
        try {
          const d = JSON.parse((ev as MessageEvent).data);
          if (d?.type === 'drop') dropNote += d.count ?? 1;
        } catch {
          /* noop */
        }
      });
      es.addEventListener('shutdown', () => {
        devmode.forceReset();
      });
      es.onerror = () => {
        /* EventSource は自動再接続する。403 は接続失敗として現れるため
           stats ポーリング側の 403 検知でリセットされる */
      };
      queueMicrotask(scrollToBottom);
      void fetchStats();
    } catch {
      /* noop */
    }
  }

  async function clearAll() {
    if (!confirm('サーバ側のログリングも含めて消去します。よろしいですか?')) return;
    try {
      const r = await fetch('/api/dev/clear', { method: 'POST' });
      if (r.status === 403) return devmode.forceReset();
      entries = [];
      gapAtTop = false;
      void fetchStats();
    } catch {
      /* noop */
    }
  }

  function toggleExpand(seq: number) {
    const next = new Set(expanded);
    if (next.has(seq)) next.delete(seq);
    else next.add(seq);
    expanded = next;
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') devmode.closePanel();
  }

  // --- ドラッグ / リサイズ / スナップ --------------------------------------
  let dragOff: { x: number; y: number } | null = null;
  function startDrag(e: MouseEvent) {
    dragOff = { x: e.clientX - box.x, y: e.clientY - box.y };
    window.addEventListener('mousemove', onDrag);
    window.addEventListener('mouseup', endDrag);
  }
  function onDrag(e: MouseEvent) {
    if (!dragOff) return;
    box = { ...box, x: Math.max(0, e.clientX - dragOff.x), y: Math.max(0, e.clientY - dragOff.y) };
  }
  function endDrag() {
    dragOff = null;
    window.removeEventListener('mousemove', onDrag);
    window.removeEventListener('mouseup', endDrag);
    persistBox();
  }
  let resizing = false;
  function startResize(e: MouseEvent) {
    e.preventDefault();
    resizing = true;
    window.addEventListener('mousemove', onResize);
    window.addEventListener('mouseup', endResize);
  }
  function onResize(e: MouseEvent) {
    if (!resizing) return;
    box = { ...box, w: Math.max(420, e.clientX - box.x), h: Math.max(240, e.clientY - box.y) };
  }
  function endResize() {
    resizing = false;
    window.removeEventListener('mousemove', onResize);
    window.removeEventListener('mouseup', endResize);
    persistBox();
  }
  function snap(kind: 'right' | 'bottom' | 'max' | 'default') {
    const W = window.innerWidth;
    const H = window.innerHeight;
    if (kind === 'right') box = { x: Math.floor(W / 2), y: 0, w: Math.floor(W / 2), h: H };
    else if (kind === 'bottom') box = { x: 0, y: Math.floor(H / 2), w: W, h: Math.floor(H / 2) };
    else if (kind === 'max') box = { x: 0, y: 0, w: W, h: H };
    else box = { x: 80, y: 80, w: 760, h: 480 };
    persistBox();
  }

  function fmtTime(ts: string): string {
    return ts.length >= 19 ? ts.slice(11, 19) : ts;
  }
  function fmtBytes(n: number): string {
    if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)}MB`;
    if (n >= 1024) return `${(n / 1024).toFixed(0)}KB`;
    return `${n}B`;
  }

  onMount(() => {
    window.addEventListener('keydown', onKeydown);
    void connect();
  });
  onDestroy(() => {
    window.removeEventListener('keydown', onKeydown);
    es?.close();
  });

  $effect(() => {
    if (tab === 'system' && system === null) void fetchSystem();
  });
</script>

<div
  class="devpanel"
  style="left:{box.x}px; top:{box.y}px; width:{box.w}px; height:{box.h}px"
  role="dialog"
  aria-label="開発者パネル"
>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="head" onmousedown={startDrag}>
    <span class="title">Dev</span>
    {#if stats}
      <span class="stats" title="entries / bytes / dropped">
        {stats.entries} 件 / {fmtBytes(stats.bytes)} / drops: {stats.dropped_total}
      </span>
    {/if}
    {#if dropNote > 0}
      <span class="drops">⚠ drop +{dropNote}</span>
    {/if}
    <span class="spacer"></span>
    <button class="hbtn" onclick={() => snap('right')} title="右半分">◨</button>
    <button class="hbtn" onclick={() => snap('bottom')} title="下半分">⬓</button>
    <button class="hbtn" onclick={() => snap('max')} title="最大化">□</button>
    <button class="hbtn" onclick={() => snap('default')} title="既定サイズ">▭</button>
    <button class="hbtn" onclick={() => devmode.closePanel()} aria-label="閉じる" title="閉じる (Esc)">×</button>
  </div>

  <div class="tabs">
    {#each ['app', 'ollama', 'server', 'events', 'system'] as t (t)}
      <button class="tab" class:active={tab === t} onclick={() => (tab = t as typeof tab)}>
        {t === 'app' ? 'App' : t === 'ollama' ? 'Ollama' : t === 'server' ? 'Server' : t === 'events' ? 'Events' : 'System'}
      </button>
    {/each}
    {#if tab !== 'system'}
      <span class="filters">
        {#each ['debug', 'info', 'warn', 'error'] as lv (lv)}
          <label class="lv"><input type="checkbox" bind:checked={levels[lv]} />{lv}</label>
        {/each}
        <input class="search" type="search" placeholder="検索" bind:value={search} />
      </span>
    {/if}
    <span class="spacer"></span>
    <a class="hbtn" href="/api/dev/export.ndjson" download title="NDJSON エクスポート">⬇</a>
    <button class="hbtn" onclick={clearAll} title="サーバリングごと消去">🗑</button>
  </div>

  {#if tab === 'system'}
    <div class="list system">
      <pre>{JSON.stringify(system, null, 2)}</pre>
    </div>
  {:else}
    <div class="list" bind:this={listEl} onscroll={onScroll}>
      {#if gapAtTop}
        <div class="gap">⚠ ここから前は失われています(容量超過)</div>
      {/if}
      {#each visible as e (e.seq)}
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div class="row lv-{e.level}" onclick={() => toggleExpand(e.seq)}>
          <span class="c-level">{e.level}</span>
          <span class="c-time">{fmtTime(e.ts)}</span>
          <span class="c-source">{e.source}</span>
          <span class="c-msg">{e.msg}</span>
        </div>
        {#if expanded.has(e.seq)}
          <pre class="detail">{JSON.stringify(e.payload, null, 2)}</pre>
        {/if}
      {/each}
    </div>
    {#if !follow}
      <button class="follow-badge" onclick={jumpToLatest}>⏸ 追従停止中 — ▶ 最新へ</button>
    {:else}
      <span class="follow-badge on">▶ 追従中</span>
    {/if}
  {/if}

  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="resize" onmousedown={startResize}></div>
</div>

<style>
  .devpanel {
    position: fixed;
    z-index: 1000;
    display: flex;
    flex-direction: column;
    background: var(--color-bg, #fff);
    border: 1px solid var(--color-border, #ccc);
    border-radius: 8px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.25);
    font-size: 12px;
    overflow: hidden;
  }
  .head {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 8px;
    background: var(--color-bg-subtle, #f3f4f6);
    border-bottom: 1px solid var(--color-border, #ccc);
    cursor: move;
    user-select: none;
  }
  .title {
    font-weight: 700;
  }
  .stats,
  .drops {
    color: var(--color-fg-muted, #666);
  }
  .drops {
    color: var(--color-error, #c00);
  }
  .spacer {
    flex: 1;
  }
  .hbtn {
    border: none;
    background: transparent;
    cursor: pointer;
    padding: 2px 6px;
    font-size: 13px;
    color: inherit;
    text-decoration: none;
  }
  .hbtn:hover {
    background: rgba(0, 0, 0, 0.08);
    border-radius: 4px;
  }
  .tabs {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 4px 8px;
    border-bottom: 1px solid var(--color-border, #ccc);
    flex-wrap: wrap;
  }
  .tab {
    border: 1px solid var(--color-border, #ccc);
    background: transparent;
    border-radius: 4px;
    padding: 2px 10px;
    cursor: pointer;
  }
  .tab.active {
    background: var(--color-accent, #3b82f6);
    color: #fff;
    border-color: var(--color-accent, #3b82f6);
  }
  .filters {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin-left: 8px;
  }
  .lv {
    display: inline-flex;
    align-items: center;
    gap: 2px;
  }
  .search {
    width: 140px;
    padding: 2px 6px;
    border: 1px solid var(--color-border, #ccc);
    border-radius: 4px;
  }
  .list {
    flex: 1;
    overflow-y: auto;
    font-family: ui-monospace, Consolas, monospace;
    padding: 4px 0;
  }
  .row {
    display: grid;
    grid-template-columns: 44px 64px 56px 1fr;
    gap: 8px;
    padding: 1px 8px;
    cursor: pointer;
    white-space: nowrap;
  }
  .row:hover {
    background: rgba(0, 0, 0, 0.05);
  }
  .c-msg {
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .lv-error .c-level {
    color: var(--color-error, #c00);
    font-weight: 700;
  }
  .lv-warn .c-level {
    color: #b45309;
  }
  .lv-debug {
    opacity: 0.65;
  }
  .detail {
    margin: 0 8px 4px 52px;
    padding: 6px;
    background: rgba(0, 0, 0, 0.05);
    border-radius: 4px;
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 240px;
    overflow-y: auto;
  }
  .gap {
    text-align: center;
    color: #b45309;
    padding: 4px;
    border-block: 1px dashed #b45309;
    margin: 4px 8px;
  }
  .system pre {
    margin: 0;
    padding: 8px;
    white-space: pre-wrap;
    word-break: break-all;
  }
  .follow-badge {
    position: absolute;
    right: 16px;
    bottom: 16px;
    border: 1px solid var(--color-border, #ccc);
    border-radius: 12px;
    padding: 2px 10px;
    background: var(--color-bg, #fff);
    cursor: pointer;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  }
  .follow-badge.on {
    opacity: 0.5;
    cursor: default;
  }
  .resize {
    position: absolute;
    right: 0;
    bottom: 0;
    width: 14px;
    height: 14px;
    cursor: nwse-resize;
    background: linear-gradient(135deg, transparent 50%, var(--color-border, #999) 50%);
  }
</style>

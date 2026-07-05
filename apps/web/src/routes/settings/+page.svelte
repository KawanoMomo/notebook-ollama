<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { ArrowLeft, Megaphone } from '@lucide/svelte';
  import { navMemoryStore } from '$lib/stores/navMemory.svelte';
  import { settingsStore } from '$lib/stores/settings.svelte';
  import { modelsStore } from '$lib/stores/models.svelte';
  import { formatBytes } from '$lib/utils/format';
  import { settingsApi } from '$lib/api/settings';
  import { openReindexEvents } from '$lib/api/reindexEvents';
  import Spinner from '$lib/components/Spinner.svelte';
  import AudioSettingsSection from '$lib/components/settings/AudioSettingsSection.svelte';
  import PromptsSection from '$lib/components/settings/PromptsSection.svelte';
  import AccelerationPanel from '$lib/components/settings/AccelerationPanel.svelte';
  import CrashReportSection from '$lib/components/settings/CrashReportSection.svelte';
  import { pushToast } from '$lib/components/Toast.svelte';
  import type { ModelInfo } from '$lib/api/types';

  let section = $state<
    'models' | 'accel' | 'gen' | 'prompts' | 'audio' | 'storage' | 'modelsList' | 'crash'
  >('audio');

  // --- 埋め込みモデル切替 (section==='models') の state ---
  // <select> の選択値。'' = 未選択(=現行と同じ。切替なし)。
  // finding 15: <option value={null}> は HTML で文字列化してぶれるため、Task 3/4 と
  // 統一して value="" を「現行/未選択」に割り当て、'' を切替なしとして正規化する。
  let pendingEmbedding = $state('');
  // 再インデックス進行状況。null = 走っていない。
  let reindex = $state<{ done: number; total: number } | null>(null);
  let switching = $state(false);
  let closeReindex: (() => void) | null = null;

  // 現行の埋め込みモデル名・次元(settings 由来)。
  const curEmbeddingModel = $derived(settingsStore.settings?.ollama.embedding_model ?? null);
  const curDim = $derived(settingsStore.settings?.ollama.embedding_dim ?? null);

  // 埋め込み用途に使えるモデル(kind が embedding | both)。
  const embeddingModels = $derived(
    modelsStore.models.filter((m) => m.kind === 'embedding' || m.kind === 'both'),
  );

  // 切替対象。'' (未選択) または現行と同じなら null(警告/ボタンを出さない)。
  const switchTarget = $derived(
    pendingEmbedding !== '' && pendingEmbedding !== curEmbeddingModel
      ? pendingEmbedding
      : null,
  );

  // 選択中(= switchTarget、未選択なら現行)のモデル情報。
  const selectedEmbedding = $derived<ModelInfo | null>(
    embeddingModels.find((m) => m.name === (switchTarget ?? curEmbeddingModel)) ?? null,
  );

  // 警告判定。
  // - 次元が現行と異なる → dim 警告。
  // - 次元は同じだが別モデル → 「再インデックス推奨」注記。
  const newDim = $derived(selectedEmbedding?.embedding_dim ?? null);
  const dimWarning = $derived(
    switchTarget !== null && newDim !== null && curDim !== null && newDim !== curDim,
  );
  const sameDimNotice = $derived(switchTarget !== null && newDim !== null && !dimWarning);

  onMount(() => {
    settingsStore.load();
    modelsStore.load();
  });

  function goBack() {
    goto(navMemoryStore.lastPath || '/');
  }

  function chatModelNames(): string[] {
    return modelsStore.models
      .filter((m) => m.kind === 'chat' || m.kind === 'both')
      .map((m) => m.name);
  }

  async function onDefaultModelChange(e: Event) {
    const select = e.currentTarget as HTMLSelectElement;
    const next = select.value;
    const prev = settingsStore.settings?.ollama.default_model ?? '';
    if (next === prev) return;
    try {
      await settingsStore.putOllama(next);
      pushToast(`既定モデルを ${next} に変更しました`, 'success');
    } catch (err) {
      select.value = prev; // 失敗時は選択を元に戻す
      const msg = err instanceof Error ? err.message : String(err);
      pushToast(`既定モデルの変更に失敗しました: ${msg}`, 'error');
    }
  }

  onDestroy(() => {
    closeReindex?.();
  });

  // --- タイムアウト設定 ---
  let timeoutDraft = $state<{ req: number; read: number } | null>(null);
  let savingTimeouts = $state(false);

  // settings の load 完了で draft 初期化
  $effect(() => {
    const ol = settingsStore.settings?.ollama;
    if (ol && timeoutDraft === null) {
      timeoutDraft = {
        req: ol.request_timeout_seconds,
        read: ol.chat_read_timeout_seconds,
      };
    }
  });

  const timeoutsDirty = $derived(
    timeoutDraft !== null &&
      settingsStore.settings !== null &&
      (timeoutDraft.req !== settingsStore.settings.ollama.request_timeout_seconds ||
        timeoutDraft.read !== settingsStore.settings.ollama.chat_read_timeout_seconds),
  );

  async function saveTimeouts() {
    if (!timeoutDraft) return;
    savingTimeouts = true;
    try {
      await settingsApi.putOllamaTimeouts(timeoutDraft.req, timeoutDraft.read);
      await settingsStore.load();
      pushToast('タイムアウトを更新しました', 'success');
    } catch (e) {
      pushToast(e instanceof Error ? e.message : String(e), 'error');
    } finally {
      savingTimeouts = false;
    }
  }

  // --- 生成設定(応答トークン上限) ---
  let genDraft = $state<{ budget: number } | null>(null);
  let savingGen = $state(false);

  $effect(() => {
    const g = settingsStore.settings?.generation;
    if (g && genDraft === null) {
      genDraft = { budget: g.response_budget_tokens };
    }
  });

  const genDirty = $derived(
    genDraft !== null &&
      settingsStore.settings !== null &&
      genDraft.budget !== settingsStore.settings.generation.response_budget_tokens,
  );

  async function saveDevMode(enabled: boolean) {
    try {
      await settingsApi.putDev(
        enabled,
        settingsStore.settings?.dev?.log_capacity_bytes,
      );
      await settingsStore.load();
      pushToast(enabled ? '開発者モードを有効にしました' : '開発者モードを無効にしました', 'success');
    } catch (e) {
      pushToast(e instanceof Error ? e.message : String(e), 'error');
    }
  }

  async function saveDevCapacity(mb: number) {
    try {
      const enabled = settingsStore.settings?.dev?.enabled ?? false;
      await settingsApi.putDev(enabled, Math.round(mb * 1048576));
      await settingsStore.load();
      pushToast('開発ログ容量を更新しました', 'success');
    } catch (e) {
      pushToast(e instanceof Error ? e.message : String(e), 'error');
    }
  }

  async function saveGeneration() {
    if (!genDraft) return;
    savingGen = true;
    try {
      await settingsApi.putGeneration(genDraft.budget);
      await settingsStore.load();
      pushToast('生成設定を更新しました', 'success');
    } catch (e) {
      pushToast(e instanceof Error ? e.message : String(e), 'error');
    } finally {
      savingGen = false;
    }
  }

  async function confirmSwitch() {
    if (!switchTarget) return;
    const target = switchTarget;
    const ok = window.confirm(
      `埋め込みモデルを「${target}」に切り替えます。全ソースを再インデックスします(数分かかる場合があります)。続行しますか?`,
    );
    if (!ok) return;

    switching = true;
    reindex = { done: 0, total: 0 };
    // 進捗 SSE を購読してから switch を投げる(取りこぼし防止)。
    closeReindex?.();
    closeReindex = openReindexEvents({
      onProgress: (ev) => {
        reindex = { done: ev.done, total: ev.total };
      },
      onComplete: async () => {
        reindex = null;
        switching = false;
        pendingEmbedding = ''; // 未選択へ戻す('' 正規化)
        closeReindex?.();
        closeReindex = null;
        await settingsStore.load();
        pushToast(`埋め込みモデルを「${target}」に切り替えました`, 'success');
      },
      onError: (ev) => {
        reindex = null;
        switching = false;
        closeReindex?.();
        closeReindex = null;
        pushToast(`再インデックスに失敗しました: ${ev.message}`, 'error');
      },
    });

    try {
      await settingsApi.switchEmbedding(target);
    } catch (e) {
      reindex = null;
      switching = false;
      closeReindex?.();
      closeReindex = null;
      pushToast(e instanceof Error ? e.message : String(e), 'error');
    }
  }
</script>

<div class="container">
  <div class="topbar">
    <button class="back" onclick={goBack} aria-label="戻る">
      <ArrowLeft size="16" />
    </button>
    <h1>設定</h1>
  </div>

  <div class="settings">
    <!-- left nav -->
    <nav class="snav">
      <div class="grp">LLM / 生成</div>
      <button
        class="nitem"
        class:active={section === 'models'}
        onclick={() => (section = 'models')}
      >
        <svg class="ni" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="4" y="4" width="16" height="16" rx="3" />
          <path d="M9 9h6v6H9z" />
        </svg>
        モデル・Ollama
      </button>
      <button
        class="nitem"
        class:active={section === 'accel'}
        onclick={() => (section = 'accel')}
      >
        <svg class="ni" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z" />
        </svg>
        アクセラレーション
      </button>
      <button
        class="nitem"
        class:active={section === 'gen'}
        onclick={() => (section = 'gen')}
      >
        <svg class="ni" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M4 6h16M4 12h16M4 18h10" />
        </svg>
        生成・検索
      </button>
      <button
        class="nitem"
        class:active={section === 'prompts'}
        onclick={() => (section = 'prompts')}
      >
        <svg class="ni" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="5" width="18" height="14" rx="2" />
          <path d="M7 10h10M7 14h6" />
        </svg>
        プロンプト
      </button>

      <div class="grp" style="margin-top:6px">入力 / 取り込み</div>
      <button
        class="nitem"
        class:active={section === 'audio'}
        onclick={() => (section = 'audio')}
      >
        <svg class="ni" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="9" y="2" width="6" height="12" rx="3" />
          <path d="M5 10a7 7 0 0 0 14 0M12 17v4" />
        </svg>
        音声・録音
      </button>

      <div class="grp" style="margin-top:6px">フィードバック</div>
      <button
        class="nitem"
        class:active={section === 'crash'}
        onclick={() => (section = 'crash')}
      >
        <Megaphone size={16} strokeWidth={1.75} class="ni" aria-hidden="true" />
        クラッシュレポート
      </button>

      <div class="grp" style="margin-top:6px">システム</div>
      <button
        class="nitem"
        class:active={section === 'storage'}
        onclick={() => (section = 'storage')}
      >
        <svg class="ni" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M4 7h16v12H4zM4 7l0-2h7l2 2" />
        </svg>
        ストレージ
      </button>
      <button
        class="nitem"
        class:active={section === 'modelsList'}
        onclick={() => (section = 'modelsList')}
      >
        <svg class="ni" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 8v4l3 2" />
        </svg>
        利用可能モデル
      </button>
    </nav>

    <!-- content panel -->
    <div class="scontent">
      {#if section === 'audio'}
        <AudioSettingsSection />
      {:else if section === 'prompts'}
        <PromptsSection />
      {:else if section === 'accel'}
        <AccelerationPanel />
      {:else if section === 'crash'}
        <CrashReportSection />
      {:else if settingsStore.loading || modelsStore.loading}
        <div class="state"><Spinner /> 読み込み中…</div>
      {:else if settingsStore.error || modelsStore.error}
        <div class="state err">
          エラー: {settingsStore.error ?? modelsStore.error}
        </div>
      {:else if settingsStore.settings && settingsStore.stats}
        {#if section === 'models'}
          <h3>モデル・Ollama</h3>
          <dl>
            <dt>エンドポイント</dt>
            <dd><code>{settingsStore.settings.ollama.endpoint}</code></dd>
            <dt>既定モデル</dt>
            <dd>
              <select
                class="model-select"
                value={settingsStore.settings.ollama.default_model}
                onchange={onDefaultModelChange}
              >
                {#each chatModelNames() as name (name)}
                  <option value={name}>{name}</option>
                {/each}
                {#if !chatModelNames().includes(settingsStore.settings.ollama.default_model)}
                  <option value={settingsStore.settings.ollama.default_model}>
                    {settingsStore.settings.ollama.default_model}(未検出)
                  </option>
                {/if}
              </select>
            </dd>
            <dt>埋め込みモデル</dt>
            <dd>
              <select
                class="emb-select"
                bind:value={pendingEmbedding}
                disabled={switching}
                aria-label="埋め込みモデル"
              >
                <option value="">{curEmbeddingModel ?? '(未設定)'}(現在)</option>
                {#each embeddingModels as m (m.name)}
                  {#if m.name !== curEmbeddingModel}
                    <option value={m.name}>
                      {m.name}{m.embedding_dim ? ` (${m.embedding_dim}次元)` : ''}
                    </option>
                  {/if}
                {/each}
              </select>
            </dd>
          </dl>

          {#if dimWarning}
            <div class="emb-warn" role="alert">
              選択したモデルは {newDim} 次元です。現在のインデックスは {curDim} 次元(既存チャンクは
              {curEmbeddingModel})。切り替えると<strong>全ソースを再インデックス</strong>します(数分かかる場合があります)。
            </div>
          {:else if sameDimNotice}
            <div class="emb-notice" role="note">
              次元は同じですが埋め込み空間が変わるため<strong>再インデックス推奨</strong>です。切り替えると全ソースを再インデックスします。
            </div>
          {/if}

          {#if switchTarget && !switching}
            <div class="emb-actions">
              <button class="emb-btn primary" onclick={confirmSwitch}>
                再インデックスして切替
              </button>
            </div>
          {/if}

          {#if switching}
            <div class="emb-progress">
              <div class="emb-bar">
                <div
                  class="emb-bar-fill"
                  style:width={reindex && reindex.total > 0
                    ? `${Math.round((reindex.done / reindex.total) * 100)}%`
                    : '8%'}
                ></div>
              </div>
              <span class="emb-progress-text">
                {#if reindex && reindex.total > 0}
                  再インデックス中… {reindex.done} / {reindex.total}
                {:else}
                  再インデックスを準備中…
                {/if}
              </span>
            </div>
          {/if}

          <h3 style="margin-top: var(--space-5)">タイムアウト</h3>
          <p class="t-hint">
            大型モデル(GPT-OSS 20B 等)で「ネットワークエラー」が出る場合に伸ばしてください。
            <code>request</code> = /api/show と /api/embeddings、<code>chat_read</code> = ストリーミング応答の最初のトークンまでの待ち時間。
          </p>
          {#if timeoutDraft}
            <dl>
              <dt>request_timeout (秒)</dt>
              <dd>
                <input
                  type="number"
                  class="num"
                  min="5"
                  max="86400"
                  step="30"
                  bind:value={timeoutDraft.req}
                  aria-label="request_timeout_seconds"
                />
              </dd>
              <dt>chat_read_timeout (秒)</dt>
              <dd>
                <input
                  type="number"
                  class="num"
                  min="5"
                  max="86400"
                  step="30"
                  bind:value={timeoutDraft.read}
                  aria-label="chat_read_timeout_seconds"
                />
              </dd>
            </dl>
            {#if timeoutsDirty}
              <div class="emb-actions">
                <button
                  class="emb-btn primary"
                  onclick={saveTimeouts}
                  disabled={savingTimeouts}
                >
                  {savingTimeouts ? '保存中…' : 'タイムアウトを保存'}
                </button>
              </div>
            {/if}
          {/if}
        {:else if section === 'gen'}
          <h3>生成</h3>
          <dl>
            <dt>context_budget_ratio</dt>
            <dd>{settingsStore.settings.generation.context_budget_ratio}</dd>
            <dt>response_budget_tokens(応答トークン上限)</dt>
            <dd>
              {#if genDraft}
                <input
                  class="num"
                  type="number"
                  min="64"
                  max="32768"
                  step="256"
                  bind:value={genDraft.budget}
                  aria-label="response_budget_tokens"
                />
                <p class="t-hint">
                  思考モデル(qwen3 等)は思考トークンもこの上限を消費します。
                  回答末尾に「上限に達したため打ち切られました」が出る場合は拡大してください。
                </p>
              {:else}
                {settingsStore.settings.generation.response_budget_tokens}
              {/if}
            </dd>
          </dl>
          {#if genDirty}
            <div class="emb-actions">
              <button
                class="emb-btn primary"
                onclick={saveGeneration}
                disabled={savingGen}
              >
                {savingGen ? '保存中…' : '生成設定を保存'}
              </button>
            </div>
          {/if}
          <h3 style="margin-top: var(--space-5)">検索</h3>
          <dl>
            <dt>top_k</dt>
            <dd>{settingsStore.settings.retrieval.top_k}</dd>
            <dt>top_k_max</dt>
            <dd>{settingsStore.settings.retrieval.top_k_max}</dd>
            <dt>min_history_turns</dt>
            <dd>{settingsStore.settings.retrieval.min_history_turns}</dd>
          </dl>
          <h3 style="margin-top: var(--space-5)">開発者モード</h3>
          <dl>
            <dt>開発者モード</dt>
            <dd>
              <input
                type="checkbox"
                checked={settingsStore.settings.dev?.enabled ?? false}
                onchange={(e) => saveDevMode((e.target as HTMLInputElement).checked)}
                aria-label="開発者モード"
              />
              <p class="t-hint">
                ON にすると、アプリロゴを 3 秒以内に 7 回クリックで Dev パネルが開きます
                (localhost のみ)。ログ収集は ON にした瞬間から始まります。
              </p>
            </dd>
            <dt>開発ログ保持容量 (MB)</dt>
            <dd>
              <input
                class="num"
                type="number"
                min="1"
                max="200"
                step="1"
                value={Math.round((settingsStore.settings.dev?.log_capacity_bytes ?? 20971520) / 1048576)}
                onchange={(e) => saveDevCapacity(Number((e.target as HTMLInputElement).value))}
                aria-label="dev_log_capacity_mb"
              />
              <p class="t-hint">1〜200 MB。超過分は古いログから捨てられます(再起動で消えます)。</p>
            </dd>
          </dl>
        {:else if section === 'storage'}
          <h3>ストレージ</h3>
          <dl>
            <dt>data_dir</dt>
            <dd><code>{settingsStore.stats.data_dir}</code></dd>
            <dt>ノートブック数</dt>
            <dd>{settingsStore.stats.notebook_count}</dd>
            <dt>ソース数</dt>
            <dd>{settingsStore.stats.source_count}</dd>
            <dt>合計チャンク数</dt>
            <dd>{settingsStore.stats.chunk_count}</dd>
          </dl>
        {:else if section === 'modelsList'}
          <h3>利用可能モデル</h3>
          <table>
            <thead>
              <tr>
                <th>名前</th>
                <th>サイズ</th>
                <th>context_window</th>
                <th>推奨用途</th>
              </tr>
            </thead>
            <tbody>
              {#each modelsStore.models as m (m.name)}
                <tr>
                  <td><code>{m.name}</code></td>
                  <td>{formatBytes(m.size_bytes)}</td>
                  <td>{m.context_window ?? '-'}</td>
                  <td>
                    {#each m.recommended_for as label}
                      <span class="tag">{label}</span>
                    {/each}
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      {/if}
    </div>
  </div>
</div>

<style>
  .container {
    max-width: 1080px;
    margin: 0 auto;
    padding: var(--space-5);
  }

  h1 {
    margin: 0 0 var(--space-4);
    font-size: 20px;
  }

  .topbar {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    margin: 0 0 var(--space-4);
  }
  .topbar h1 {
    margin: 0;
  }
  .back {
    background: none;
    border: none;
    color: var(--color-fg-muted);
    padding: var(--space-1);
    border-radius: var(--radius-sm);
    display: inline-flex;
    cursor: pointer;
  }
  .back:hover {
    background: var(--color-bg-elevated);
    color: var(--color-fg);
  }

  .settings {
    display: grid;
    grid-template-columns: 210px 1fr;
    min-height: 560px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    overflow: hidden;
    background: var(--color-bg);
    box-shadow: 0 4px 18px rgba(0, 0, 0, 0.07);
  }

  /* Left nav */
  .snav {
    border-right: 1px solid var(--color-border);
    background: var(--color-bg-sidebar);
    padding: 14px 10px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .grp {
    font-size: 10px;
    color: var(--color-fg-muted);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 10px 10px 4px;
  }

  .nitem {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 8px 10px;
    border-radius: var(--radius-md);
    font-size: 13px;
    color: var(--color-fg);
    background: none;
    border: none;
    text-align: left;
    width: 100%;
    cursor: pointer;
  }

  .nitem:hover {
    background: #ececed;
  }

  .nitem.active {
    background: var(--color-accent);
    color: #fff;
  }

  .ni {
    width: 16px;
    height: 16px;
    color: var(--color-fg-muted);
    flex-shrink: 0;
    display: block;
  }

  .nitem.active .ni {
    color: #fff;
  }

  /* Content area */
  .scontent {
    padding: 22px 26px;
    overflow-y: auto;
  }

  h3 {
    margin: 0 0 var(--space-1);
    font-size: 17px;
  }

  dl {
    display: grid;
    grid-template-columns: 200px 1fr;
    gap: var(--space-2) var(--space-4);
    margin: 0;
  }

  dt {
    color: var(--color-fg-muted);
    font-size: 13px;
  }

  dd {
    margin: 0;
    font-size: 13px;
  }

  .model-select {
    font-size: 13px;
    padding: 4px 8px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-bg);
    color: var(--color-fg);
    min-width: 240px;
    font-family: var(--font-mono);
  }

  code {
    font-family: var(--font-mono);
    font-size: 12px;
    background: var(--color-bg-elevated);
    padding: 1px var(--space-2);
    border-radius: var(--radius-sm);
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }

  th,
  td {
    text-align: left;
    padding: var(--space-2) var(--space-3);
    border-bottom: 1px solid var(--color-border);
  }

  th {
    font-size: 11px;
    color: var(--color-fg-muted);
    text-transform: uppercase;
  }

  .tag {
    background: var(--color-bg-elevated);
    padding: 1px var(--space-2);
    border-radius: var(--radius-sm);
    font-size: 11px;
    margin-right: var(--space-1);
  }

  .state {
    text-align: center;
    padding: var(--space-5);
    color: var(--color-fg-muted);
  }

  .err {
    color: var(--color-error);
  }

  .emb-select {
    font: inherit;
    font-size: 13px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: 5px 9px;
    background: var(--color-bg);
    min-width: 240px;
  }

  .emb-warn,
  .emb-notice {
    margin-top: var(--space-3);
    padding: 10px 12px;
    border-radius: var(--radius-md);
    font-size: 12px;
    line-height: 1.6;
  }

  .emb-warn {
    background: #fff4e5;
    border: 1px solid #f0c27a;
    color: #8a5300;
  }

  .emb-notice {
    background: var(--color-bg-elevated);
    border: 1px solid var(--color-border);
    color: var(--color-fg-muted);
  }

  .emb-actions {
    margin-top: var(--space-3);
  }

  .emb-btn {
    border: 1px solid var(--color-border);
    background: var(--color-bg);
    color: var(--color-fg);
    border-radius: var(--radius-md);
    padding: 7px 14px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
  }

  .emb-btn.primary {
    background: var(--color-accent);
    border-color: var(--color-accent);
    color: #fff;
  }

  .emb-progress {
    margin-top: var(--space-4);
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    max-width: 360px;
  }

  .emb-bar {
    height: 8px;
    border-radius: 999px;
    background: var(--color-bg-elevated);
    overflow: hidden;
  }

  .emb-bar-fill {
    height: 100%;
    background: var(--color-accent);
    transition: width 0.2s ease;
  }

  .emb-progress-text {
    font-size: 12px;
    color: var(--color-fg-muted);
  }
  .t-hint {
    margin: 0 0 var(--space-3);
    font-size: 12px;
    color: var(--color-fg-muted);
    line-height: 1.55;
  }
  .num {
    font-size: 13px;
    padding: 4px 8px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-bg);
    color: var(--color-fg);
    width: 120px;
    font-variant-numeric: tabular-nums;
  }
</style>

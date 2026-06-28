<script lang="ts">
  import { onMount } from 'svelte';
  import { settingsStore } from '$lib/stores/settings.svelte';
  import { modelsStore } from '$lib/stores/models.svelte';
  import { formatBytes } from '$lib/utils/format';
  import Spinner from '$lib/components/Spinner.svelte';
  import AudioSettingsSection from '$lib/components/settings/AudioSettingsSection.svelte';

  let section = $state<'models' | 'gen' | 'audio' | 'storage' | 'modelsList'>('audio');

  onMount(() => {
    settingsStore.load();
    modelsStore.load();
  });
</script>

<div class="container">
  <h1>設定</h1>

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
        class:active={section === 'gen'}
        onclick={() => (section = 'gen')}
      >
        <svg class="ni" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M4 6h16M4 12h16M4 18h10" />
        </svg>
        生成・検索
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
            <dd><code>{settingsStore.settings.ollama.default_model}</code></dd>
            <dt>埋め込みモデル</dt>
            <dd><code>{settingsStore.settings.ollama.embedding_model}</code></dd>
          </dl>
        {:else if section === 'gen'}
          <h3>生成</h3>
          <dl>
            <dt>context_budget_ratio</dt>
            <dd>{settingsStore.settings.generation.context_budget_ratio}</dd>
            <dt>response_budget_tokens</dt>
            <dd>{settingsStore.settings.generation.response_budget_tokens}</dd>
          </dl>
          <h3 style="margin-top: var(--space-5)">検索</h3>
          <dl>
            <dt>top_k</dt>
            <dd>{settingsStore.settings.retrieval.top_k}</dd>
            <dt>top_k_max</dt>
            <dd>{settingsStore.settings.retrieval.top_k_max}</dd>
            <dt>min_history_turns</dt>
            <dd>{settingsStore.settings.retrieval.min_history_turns}</dd>
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
</style>

<script lang="ts">
  import { onMount } from 'svelte';
  import { settingsStore } from '$lib/stores/settings.svelte';
  import { modelsStore } from '$lib/stores/models.svelte';
  import { formatBytes } from '$lib/utils/format';
  import Spinner from '$lib/components/Spinner.svelte';

  onMount(() => {
    settingsStore.load();
    modelsStore.load();
  });
</script>

<div class="container">
  <h1>設定</h1>

  {#if settingsStore.loading || modelsStore.loading}
    <div class="state"><Spinner /> 読み込み中…</div>
  {:else if settingsStore.error || modelsStore.error}
    <div class="state err">
      エラー: {settingsStore.error ?? modelsStore.error}
    </div>
  {:else if settingsStore.settings && settingsStore.stats}
    <section>
      <h2>Ollama</h2>
      <dl>
        <dt>エンドポイント</dt>
        <dd><code>{settingsStore.settings.ollama.endpoint}</code></dd>
        <dt>既定モデル</dt>
        <dd><code>{settingsStore.settings.ollama.default_model}</code></dd>
        <dt>埋め込みモデル</dt>
        <dd><code>{settingsStore.settings.ollama.embedding_model}</code></dd>
      </dl>
    </section>

    <section>
      <h2>生成</h2>
      <dl>
        <dt>context_budget_ratio</dt>
        <dd>{settingsStore.settings.generation.context_budget_ratio}</dd>
        <dt>response_budget_tokens</dt>
        <dd>{settingsStore.settings.generation.response_budget_tokens}</dd>
      </dl>
    </section>

    <section>
      <h2>検索</h2>
      <dl>
        <dt>top_k</dt><dd>{settingsStore.settings.retrieval.top_k}</dd>
        <dt>top_k_max</dt><dd>{settingsStore.settings.retrieval.top_k_max}</dd>
        <dt>min_history_turns</dt>
        <dd>{settingsStore.settings.retrieval.min_history_turns}</dd>
      </dl>
    </section>

    <section>
      <h2>ストレージ</h2>
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
    </section>

    <section>
      <h2>利用可能モデル</h2>
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
    </section>
  {/if}
</div>

<style>
  .container {
    max-width: 800px;
    margin: 0 auto;
    padding: var(--space-5);
  }
  h1 {
    margin: 0 0 var(--space-5);
  }
  section {
    margin-bottom: var(--space-5);
  }
  h2 {
    font-size: 14px;
    margin: 0 0 var(--space-3);
    color: var(--color-fg-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
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

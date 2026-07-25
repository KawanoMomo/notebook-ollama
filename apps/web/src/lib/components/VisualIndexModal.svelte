<script lang="ts">
  import Modal from './Modal.svelte';
  import Spinner from './Spinner.svelte';
  import type { VisualIndexStatus } from '$lib/api/visualIndex';

  interface Progress {
    done: number;
    total: number;
  }

  interface Props {
    notebookId: string;
    status: VisualIndexStatus;
    progress?: Progress | null;
    onBuild: () => void;
    onDelete: () => void;
    onClose: () => void;
  }
  // notebookId は呼び出し元(SourcesPanel)とのインタフェース合わせのため受け取るのみで、
  // このコンポーネント自体は表示専用のため参照しない。
  let { status, progress = null, onBuild, onDelete, onClose }: Props = $props();

  let buildDisabled = $derived(status.building || !status.extra_available);

  /** ISO-8601 をユーザのローカル時刻で整形する。パース失敗時は元の文字列を返す
   * (BugReportTab.svelte の formatDate と同じ方針)。 */
  function formatDate(iso: string): string {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString('ja-JP');
  }
</script>

<Modal title="視覚インデックス" {onClose}>
  <div class="visual-index">
    {#if !status.extra_available}
      <p class="hint">この機能には `uv sync --extra visual` が必要です</p>
    {/if}

    {#if status.built}
      <p class="status">
        構築済み: {status.embedding_model}（{status.built_at ? formatDate(status.built_at) : '日時不明'}）
      </p>
      <p class="status">
        ソース {status.indexed_sources} 件 / 未索引 {status.pending_sources} 件
      </p>
    {:else}
      <p class="status">未構築です</p>
    {/if}

    {#if status.building}
      <p class="progress">
        <Spinner size={14} />
        構築中… {#if progress}{progress.done} / {progress.total}{:else}0 / 0{/if}
      </p>
    {/if}

    <div class="actions">
      <button type="button" onclick={onBuild} disabled={buildDisabled}>
        視覚インデックスを構築
      </button>
      {#if status.built}
        <button type="button" class="danger" onclick={onDelete}>
          視覚インデックスを削除
        </button>
      {/if}
    </div>
  </div>
</Modal>

<style>
  .visual-index {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 320px;
  }
  .status {
    margin: 0;
    font-size: 13px;
    color: var(--color-fg);
  }
  .hint {
    margin: 0;
    font-size: 12px;
    color: var(--color-warning, #b45309);
    font-family: var(--font-mono);
  }
  .progress {
    margin: 0;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: 13px;
    color: var(--color-fg-muted);
  }
  .actions {
    display: flex;
    gap: var(--space-2);
    margin-top: var(--space-2);
  }
  .actions button {
    font: inherit;
    font-size: 13px;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    border: 1px solid var(--color-border);
    background: var(--color-accent);
    color: #fff;
    cursor: pointer;
  }
  .actions button:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .actions button.danger {
    background: var(--color-bg);
    color: var(--color-error);
    border-color: var(--color-error);
  }
</style>

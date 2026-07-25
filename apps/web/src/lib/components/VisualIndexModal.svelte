<script lang="ts">
  import Modal from './Modal.svelte';
  import Spinner from './Spinner.svelte';
  import type { VisualIndexStatus } from '$lib/api/visualIndex';

  interface Progress {
    done: number;
    total: number;
    etaSeconds?: number | null;
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
  let deleteArmed = $state(false);

  /** ISO-8601 をユーザのローカル時刻で整形する。パース失敗時は元の文字列を返す
   * (BugReportTab.svelte の formatDate と同じ方針)。 */
  function formatDate(iso: string): string {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString('ja-JP');
  }

  /** 残り時間目安の表示文言。CPU推論では1ページ数十秒かかるため、目安表示は
   * ADRドラフト(visual-embedding-ondemand-transformers)が求める要件。 */
  function formatEta(seconds: number): string {
    if (seconds < 60) return '残り目安 1分未満';
    return `残り目安 約${Math.ceil(seconds / 60)}分`;
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
        {#if progress?.etaSeconds != null}
          <span class="eta">（{formatEta(progress.etaSeconds)}）</span>
        {/if}
      </p>
    {/if}

    <div class="actions">
      <button type="button" onclick={onBuild} disabled={buildDisabled}>
        視覚インデックスを構築
      </button>
      {#if status.built}
        <button
          type="button"
          class={deleteArmed ? 'danger armed' : 'danger'}
          onclick={() => {
            if (deleteArmed) {
              onDelete();
              deleteArmed = false;
            } else {
              deleteArmed = true;
            }
          }}
        >
          {deleteArmed ? '本当に削除' : '視覚インデックスを削除'}
        </button>
        {#if deleteArmed}
          <button type="button" class="cancel" onclick={() => (deleteArmed = false)}>
            やめる
          </button>
        {/if}
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
  .eta {
    color: var(--color-fg-muted);
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
  .actions button.danger.armed {
    background: var(--color-error);
    color: #fff;
    border-color: var(--color-error);
  }
  .actions button.cancel {
    background: var(--color-bg);
    color: var(--color-fg);
    border-color: var(--color-border);
  }
</style>

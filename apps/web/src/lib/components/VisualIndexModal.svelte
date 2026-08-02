<script lang="ts">
  import type { VisualIndexStatus, VisualIndexUnit, VisualUnitStatus } from '$lib/api/visualIndex';
  import { VISUAL_INDEX_UNITS, VISUAL_UNIT_LABELS } from '$lib/api/visualIndex';
  import Modal from './Modal.svelte';
  import Spinner from './Spinner.svelte';

  interface Progress {
    done: number;
    total: number;
    etaSeconds?: number | null;
  }

  interface Props {
    notebookId: string;
    status: VisualIndexStatus;
    progressFor: (unit: VisualIndexUnit) => Progress | null;
    onBuild: (unit: VisualIndexUnit) => void;
    onDelete: (unit: VisualIndexUnit) => void;
    onClose: () => void;
  }
  // notebookId は呼び出し元(SourcesPanel)とのインタフェース合わせのため受け取るのみで、
  // このコンポーネント自体は表示専用のため参照しない。
  let { status, progressFor, onBuild, onDelete, onClose }: Props = $props();

  // 行ごとに削除の2段階確認を持つ。単一の状態にすると片方を押したときに
  // もう片方まで「本当に削除」表示になる。
  let deleteArmed = $state<Record<VisualIndexUnit, boolean>>({ page: false, tile: false });

  function unitOf(unit: VisualIndexUnit): VisualUnitStatus {
    return status.units[unit];
  }

  function buildDisabled(unit: VisualIndexUnit): boolean {
    return unitOf(unit).building || !status.extra_available;
  }

  function formatDate(iso: string): string {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString('ja-JP');
  }

  function formatEta(seconds: number): string {
    if (seconds < 60) return '残り目安 1分未満';
    return `残り目安 約${Math.ceil(seconds / 60)}分`;
  }

  function onDeleteClick(unit: VisualIndexUnit) {
    if (deleteArmed[unit]) {
      onDelete(unit);
      deleteArmed = { ...deleteArmed, [unit]: false };
    } else {
      deleteArmed = { ...deleteArmed, [unit]: true };
    }
  }
</script>

<Modal title="視覚インデックス" {onClose}>
  <div class="visual-index">
    {#if !status.extra_available}
      <p class="hint">
        視覚埋め込みの依存が未導入です。<code>uv sync --extra visual</code> を実行してください。
      </p>
    {/if}

    {#each VISUAL_INDEX_UNITS as unit (unit)}
      {@const u = unitOf(unit)}
      {@const progress = progressFor(unit)}
      <section class="row" role="group" aria-label={VISUAL_UNIT_LABELS[unit]}>
        <div class="row-head">
          <h3>{VISUAL_UNIT_LABELS[unit]}</h3>
          {#if status.index_unit === unit}
            <span class="badge">検索に使用中</span>
          {/if}
        </div>

        {#if u.built}
          <p class="state">
            構築済み {u.indexed_sources} ソース
            {#if u.pending_sources > 0}／未索引 {u.pending_sources} ソース{/if}
            {#if u.embedding_model}<br /><small>{u.embedding_model}</small>{/if}
            {#if u.built_at}<br /><small>{formatDate(u.built_at)}</small>{/if}
          </p>
        {:else}
          <p class="state">
            未構築です
            {#if u.pending_sources > 0}(対象 {u.pending_sources} ソース){/if}
          </p>
        {/if}

        {#if u.building && progress}
          <p class="progress">
            <Spinner size={14} />
            {progress.done} / {progress.total}
            {#if progress.etaSeconds != null}
              <span class="eta">{formatEta(progress.etaSeconds)}</span>
            {/if}
          </p>
        {/if}

        <div class="actions">
          <button
            type="button"
            disabled={buildDisabled(unit)}
            onclick={() => onBuild(unit)}>{VISUAL_UNIT_LABELS[unit]}を構築</button
          >
          {#if u.built}
            <button
              type="button"
              class={deleteArmed[unit] ? 'danger armed' : 'danger'}
              onclick={() => onDeleteClick(unit)}
              >{deleteArmed[unit]
                ? `本当に${VISUAL_UNIT_LABELS[unit]}を削除`
                : `${VISUAL_UNIT_LABELS[unit]}を削除`}</button
            >
            {#if deleteArmed[unit]}
              <button
                type="button"
                class="cancel"
                onclick={() => (deleteArmed = { ...deleteArmed, [unit]: false })}
                >{VISUAL_UNIT_LABELS[unit]}の削除をやめる</button
              >
            {/if}
          {/if}
        </div>
      </section>
    {/each}
  </div>
</Modal>

<style>
  .visual-index {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 320px;
  }
  .hint {
    margin: 0;
    font-size: 12px;
    color: var(--color-warning, #b45309);
    font-family: var(--font-mono);
  }
  .state {
    margin: 0;
    font-size: 13px;
    color: var(--color-fg);
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
  .row {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    padding: var(--space-2) 0;
  }
  .row + .row {
    border-top: 1px solid var(--color-border);
  }
  .row-head {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .row-head h3 {
    margin: 0;
    font-size: 0.95rem;
  }
  .badge {
    font-size: 0.75rem;
    padding: 2px var(--space-2);
    border-radius: var(--radius-sm);
    background: var(--color-bg-elevated);
    border: 1px solid var(--color-accent);
    color: var(--color-accent);
  }
  /* .dialog は min-width:400px 固定。2行 x 最大3ボタンで溢れるため折り返す */
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
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

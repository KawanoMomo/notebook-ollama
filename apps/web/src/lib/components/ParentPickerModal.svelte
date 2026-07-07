<script lang="ts">
  /**
   * ParentPickerModal — SourcesPanel の「親ソースを設定」で開く候補選択モーダル。
   * 仕様: docs/specs/2026-07-06-presentation-mode-design.md, Task 10 brief。
   *
   * 候補一覧(自身と自身の子孫を除いたソース)は呼び出し元(SourcesPanel)が
   * 用意して渡す。既存 Modal.svelte の shell(背景クリック/Esc/×で onClose)を
   * そのまま使う。
   */
  import Modal from './Modal.svelte';
  import type { Source } from '$lib/api/types';

  interface Props {
    candidates: Source[];
    onPick: (id: string) => void;
    onClose: () => void;
  }
  let { candidates, onPick, onClose }: Props = $props();
</script>

<Modal title="親ソースを設定" {onClose}>
  {#if candidates.length === 0}
    <p class="empty">リンク可能なソースがありません</p>
  {:else}
    <ul class="list">
      {#each candidates as c (c.id)}
        <li>
          <button class="candidate" onclick={() => onPick(c.id)}>
            {c.title ?? c.origin ?? '無題'}
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</Modal>

<style>
  .list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    min-width: 280px;
    max-height: 320px;
    overflow: auto;
  }
  .candidate {
    display: block;
    width: 100%;
    text-align: left;
    background: none;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-2) var(--space-3);
    font-size: 13px;
    cursor: pointer;
  }
  .candidate:hover {
    background: var(--color-bg-elevated);
    border-color: var(--color-accent);
  }
  .empty {
    color: var(--color-fg-muted);
    font-size: 13px;
    text-align: center;
    padding: var(--space-4) 0;
    margin: 0;
  }
</style>

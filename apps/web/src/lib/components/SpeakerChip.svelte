<script lang="ts">
  interface Props {
    // 表示する話者ラベル。
    speaker: string;
    // 任意: 色付きドット / chip 背景色。未指定なら中立色。
    color?: string;
    // 任意: 渡されたときだけ chip をクリック編集可能にする(後方互換)。
    // (fromLabel, toLabel) を親に通知し、親が API 呼び出し + 表示更新を担う。
    onRename?: (fromLabel: string, toLabel: string) => void;
  }
  let { speaker, color, onRename }: Props = $props();

  let chipColor = $derived(color ?? 'var(--color-fg-muted)');

  // 話者チップのインライン編集。
  // onRename が渡されたときのみ編集可。Enter/✓ で確定、Esc/✕ で取消。
  // 確定値が空 or 変更なし(空白のみ含む)なら親へ通知しない (no-op)。
  let editing = $state(false);
  let editValue = $state('');

  function startEdit() {
    if (!onRename) return;
    editValue = speaker;
    editing = true;
  }

  function commitEdit() {
    if (!editing) return;
    editing = false;
    const next = editValue.trim();
    const from = speaker;
    if (!next || next === from || !from) return;
    onRename?.(from, next);
  }

  function cancelEdit() {
    editing = false;
  }

  function onEditKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault();
      commitEdit();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cancelEdit();
    }
  }
</script>

{#if editing}
  <span class="spk-edit">
    <span class="dot" style="background:{chipColor}"></span>
    <!-- svelte-ignore a11y_autofocus -->
    <input
      class="spk-input"
      type="text"
      bind:value={editValue}
      onkeydown={onEditKeydown}
      autofocus
      aria-label="話者名を編集"
    />
    <button class="spk-act ok" type="button" onclick={commitEdit} aria-label="確定" title="確定"
      >✓</button
    >
    <button
      class="spk-act cancel"
      type="button"
      onclick={cancelEdit}
      aria-label="取消"
      title="取消">✕</button
    >
  </span>
{:else if onRename}
  <button
    class="spk-chip editable"
    type="button"
    style="background:{chipColor}"
    onclick={startEdit}
    aria-label="話者名を編集"
    title="クリックで話者名を編集">● {speaker}</button
  >
{:else}
  <span class="spk-chip" style="background:{chipColor}">● {speaker}</span>
{/if}

<style>
  .spk-chip {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    font-size: 11px;
    font-weight: 600;
    border-radius: 999px;
    padding: 2px 9px;
    color: #fff;
    flex: none;
  }
  /* クリック編集可の chip は button だが見た目は span と同一にする。 */
  button.spk-chip {
    border: none;
    cursor: pointer;
    font: inherit;
    font-size: 11px;
    font-weight: 600;
    line-height: 1.2;
  }
  button.spk-chip.editable:hover {
    filter: brightness(1.08);
  }
  .spk-edit {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
  }
  .spk-edit .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex: none;
  }
  .spk-input {
    width: 9em;
    min-width: 0;
    font-size: 11px;
    font-weight: 600;
    border: 1px solid var(--color-accent);
    border-radius: var(--radius-sm);
    padding: 1px var(--space-1);
  }
  .spk-act {
    border: none;
    background: none;
    padding: 0 2px;
    font-size: 12px;
    line-height: 1;
    cursor: pointer;
  }
  .spk-act.ok {
    color: var(--color-success);
  }
  .spk-act.cancel {
    color: var(--color-fg-muted);
  }
  .spk-act:hover {
    filter: brightness(0.85);
  }
</style>

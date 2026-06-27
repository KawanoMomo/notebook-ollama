<script lang="ts">
  import { onMount } from 'svelte';
  import FixedSlotCard from './FixedSlotCard.svelte';
  import DropdownPromptEditModal from './DropdownPromptEditModal.svelte';
  import { promptsStore } from '$lib/stores/prompts.svelte';
  import { pushToast } from '../Toast.svelte';
  import { ArrowUp, ArrowDown, Edit2, Trash2, Plus } from '@lucide/svelte';
  import Spinner from '../Spinner.svelte';
  import type { DropdownPromptOut } from '$lib/api/types';

  let editing = $state<{ id?: string; title: string; body: string } | null>(null);

  onMount(() => {
    if (!promptsStore.prompts) {
      promptsStore.load();
    }
  });

  function asSlot(i: number): 0 | 1 | 2 {
    return i as 0 | 1 | 2;
  }

  // 固定スロット用のクロージャ群(各カードに固有の slot index を束縛して渡す)
  function saveFixed(i: 0 | 1 | 2) {
    return async (title: string, body: string) => {
      await promptsStore.saveFixed(i, title, body);
      if (promptsStore.error) {
        pushToast(promptsStore.error, 'error');
        return;
      }
      pushToast('スロットを保存しました', 'success');
    };
  }
  function clearFixed(i: 0 | 1 | 2) {
    return async () => {
      if (!confirm(`スロット ${i + 1} を空にしますか?`)) return;
      await promptsStore.clearFixed(i);
      if (promptsStore.error) pushToast(promptsStore.error, 'error');
      else pushToast('スロットを空にしました', 'success');
    };
  }
  function uploadIcon(i: 0 | 1 | 2) {
    return async (file: File) => {
      await promptsStore.uploadIcon(i, file);
      if (promptsStore.error) pushToast(promptsStore.error, 'error');
      else pushToast('画像を保存しました', 'success');
    };
  }
  function deleteIcon(i: 0 | 1 | 2) {
    return async () => {
      await promptsStore.deleteIcon(i);
      if (promptsStore.error) pushToast(promptsStore.error, 'error');
    };
  }

  // プルダウン
  async function onMove(d: DropdownPromptOut, delta: -1 | 1) {
    await promptsStore.moveDropdown(d.id, delta);
    if (promptsStore.error) pushToast(promptsStore.error, 'error');
  }
  async function onDelete(d: DropdownPromptOut) {
    if (!confirm(`「${d.title}」を削除しますか?`)) return;
    await promptsStore.deleteDropdown(d.id);
    if (promptsStore.error) pushToast(promptsStore.error, 'error');
    else pushToast('削除しました', 'success');
  }
  function onEdit(d: DropdownPromptOut) {
    editing = { id: d.id, title: d.title, body: d.body };
  }
  function onAdd() {
    editing = { title: '', body: '' };
  }
  async function onSaveEdit(title: string, body: string) {
    if (editing?.id) {
      await promptsStore.updateDropdown(editing.id, title, body);
    } else {
      await promptsStore.addDropdown(title, body);
    }
    if (promptsStore.error) {
      pushToast(promptsStore.error, 'error');
      return;
    }
    pushToast('保存しました', 'success');
  }

  const dropdown = $derived(promptsStore.prompts?.dropdown ?? []);
  const dropdownAtLimit = $derived(dropdown.length >= 100);
</script>

<h3>プロンプト</h3>
<p class="hint">
  チャット入力欄上の「プロンプト挿入ツールバー」で使う定型プロンプトを登録します。
  固定 3 ボタンに加え、プルダウンから任意件数(最大 100 件)を発行できます。
</p>

{#if promptsStore.loading && !promptsStore.prompts}
  <div class="state"><Spinner /> 読み込み中…</div>
{:else if !promptsStore.prompts}
  <div class="state err">読み込みに失敗しました</div>
{:else}
  <h4 style="margin-top: var(--space-4)">固定ボタン(3 スロット)</h4>
  <div class="slot-grid">
    {#each promptsStore.prompts.fixed as slot, i (i)}
      <FixedSlotCard
        {slot}
        slotIndex={asSlot(i)}
        onSave={saveFixed(asSlot(i))}
        onClear={clearFixed(asSlot(i))}
        onUploadIcon={uploadIcon(asSlot(i))}
        onDeleteIcon={deleteIcon(asSlot(i))}
      />
    {/each}
  </div>

  <h4 style="margin-top: var(--space-5)">プルダウン候補</h4>
  <p class="hint sub">
    {dropdown.length} / 100 件
  </p>
  {#if dropdown.length === 0}
    <p class="empty-row">まだ登録されていません</p>
  {:else}
    <table class="ptable">
      <thead>
        <tr>
          <th>タイトル</th>
          <th class="actions-col">操作</th>
        </tr>
      </thead>
      <tbody>
        {#each dropdown as d, idx (d.id)}
          <tr>
            <td class="ttl">{d.title}</td>
            <td class="actions-col">
              <button
                class="icon-btn"
                onclick={() => onMove(d, -1)}
                disabled={idx === 0}
                aria-label="上へ"
              >
                <ArrowUp size="13" />
              </button>
              <button
                class="icon-btn"
                onclick={() => onMove(d, 1)}
                disabled={idx === dropdown.length - 1}
                aria-label="下へ"
              >
                <ArrowDown size="13" />
              </button>
              <button
                class="icon-btn"
                onclick={() => onEdit(d)}
                aria-label="編集"
              >
                <Edit2 size="13" />
              </button>
              <button
                class="icon-btn danger"
                onclick={() => onDelete(d)}
                aria-label="削除"
              >
                <Trash2 size="13" />
              </button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
  <div class="add-row">
    <button class="add-btn" onclick={onAdd} disabled={dropdownAtLimit}>
      <Plus size="13" /> プルダウンに追加
    </button>
    {#if dropdownAtLimit}
      <span class="warn">上限 100 件に達しています</span>
    {/if}
  </div>
{/if}

{#if editing}
  <DropdownPromptEditModal
    initial={editing}
    onClose={() => (editing = null)}
    onSave={onSaveEdit}
  />
{/if}

<style>
  .hint {
    font-size: 12px;
    color: var(--color-fg-muted);
    line-height: 1.55;
    margin: 0 0 var(--space-3);
  }
  .hint.sub {
    margin-bottom: var(--space-2);
  }
  h4 {
    font-size: 13px;
    margin: 0 0 var(--space-2);
    color: var(--color-fg);
  }
  .slot-grid {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .ptable {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }
  .ptable th,
  .ptable td {
    text-align: left;
    padding: var(--space-2) var(--space-3);
    border-bottom: 1px solid var(--color-border);
  }
  .ptable th {
    font-size: 11px;
    color: var(--color-fg-muted);
    text-transform: uppercase;
  }
  .ttl {
    word-break: break-all;
  }
  .actions-col {
    width: 1%;
    white-space: nowrap;
  }
  .icon-btn {
    background: none;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    color: var(--color-fg-muted);
    padding: 3px 5px;
    margin-left: 2px;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
  }
  .icon-btn:hover:not(:disabled) {
    color: var(--color-fg);
    border-color: var(--color-accent);
  }
  .icon-btn:disabled {
    opacity: 0.35;
    cursor: not-allowed;
  }
  .icon-btn.danger:hover:not(:disabled) {
    color: var(--color-error);
  }
  .empty-row {
    font-size: 12px;
    color: var(--color-fg-muted);
    text-align: center;
    padding: var(--space-3);
    border: 1px dashed var(--color-border);
    border-radius: var(--radius-sm);
  }
  .add-row {
    margin-top: var(--space-3);
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .add-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    padding: 5px 10px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--color-border);
    background: var(--color-bg);
    cursor: pointer;
  }
  .add-btn:hover:not(:disabled) {
    border-color: var(--color-accent);
    color: var(--color-accent);
  }
  .add-btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }
  .warn {
    font-size: 12px;
    color: var(--color-error);
  }
  .state {
    text-align: center;
    padding: var(--space-5);
    color: var(--color-fg-muted);
  }
  .state.err {
    color: var(--color-error);
  }
</style>

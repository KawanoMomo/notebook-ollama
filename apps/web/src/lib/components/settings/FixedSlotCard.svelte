<script lang="ts">
  import type { FixedPromptSlotOut } from '$lib/api/types';
  import { Upload, Trash2, FileText } from '@lucide/svelte';

  interface Props {
    slot: FixedPromptSlotOut;
    slotIndex: 0 | 1 | 2;
    onSave: (title: string, body: string) => Promise<void>;
    onClear: () => Promise<void>;
    onUploadIcon: (file: File) => Promise<void>;
    onDeleteIcon: () => Promise<void>;
  }
  let {
    slot,
    slotIndex,
    onSave,
    onClear,
    onUploadIcon,
    onDeleteIcon,
  }: Props = $props();

  // ローカル下書き。prop 更新時に同期する($effect 内で外部更新を取り込む)。
  let title = $state(slot.title);
  let body = $state(slot.body);
  let saving = $state(false);

  $effect(() => {
    title = slot.title;
    body = slot.body;
  });

  let iconInputEl: HTMLInputElement | null = null;
  let mdInputEl: HTMLInputElement | null = null;

  async function onIconChange(e: Event) {
    const input = e.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    // クライアント側の早期検査(設計 §6.2)。
    const allowed = ['image/png', 'image/jpeg', 'image/svg+xml'];
    if (!allowed.includes(file.type)) {
      alert('対応形式は PNG / JPG / SVG です');
      return;
    }
    if (file.size > 200 * 1024) {
      alert('画像サイズは 200KB 以下にしてください');
      return;
    }
    await onUploadIcon(file);
  }

  async function onMdImport(e: Event) {
    const input = e.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    const lower = file.name.toLowerCase();
    if (!lower.endsWith('.md') && !lower.endsWith('.markdown')) {
      alert('.md / .markdown ファイルを選んでください');
      return;
    }
    const text = await file.text();
    if (text.length > 10_000) {
      alert('プロンプト本文は 10,000 文字以下にしてください');
      return;
    }
    body = text;
  }

  async function handleSave() {
    saving = true;
    try {
      await onSave(title, body);
    } finally {
      saving = false;
    }
  }

  const canSave = $derived(
    !saving && title.trim() !== '' && body.trim() !== '',
  );
</script>

<div class="slot-card">
  <div class="head">
    <div class="preview" aria-label="アイコンプレビュー">
      {#if slot.icon_url}
        <img src={slot.icon_url} alt="" />
      {:else if title}
        <span class="head-char">{title.slice(0, 1)}</span>
      {:else}
        <span class="head-empty">—</span>
      {/if}
    </div>
    <div class="slot-no">スロット {slotIndex + 1}</div>
  </div>

  <label>
    タイトル
    <input
      type="text"
      class="text-input"
      bind:value={title}
      maxlength="100"
      placeholder="例: 要約 / 翻訳 / 校正"
    />
  </label>

  <label>
    プロンプト本文
    <textarea
      class="body-input"
      bind:value={body}
      maxlength="10000"
      rows="4"
      placeholder="クリック時に送信される本文を入力"
    ></textarea>
  </label>

  <div class="actions">
    <button
      type="button"
      class="ghost"
      onclick={() => iconInputEl?.click()}
    >
      <Upload size="13" /> 画像を選択…
    </button>
    {#if slot.icon_url}
      <button type="button" class="ghost danger" onclick={onDeleteIcon}>
        <Trash2 size="13" /> 画像を削除
      </button>
    {/if}
    <button type="button" class="ghost" onclick={() => mdInputEl?.click()}>
      <FileText size="13" /> Markdown ファイルからインポート…
    </button>
    <div class="spacer"></div>
    <button type="button" class="ghost danger" onclick={onClear}>
      スロットを空に
    </button>
    <button
      type="button"
      class="primary"
      disabled={!canSave}
      onclick={handleSave}
    >
      保存
    </button>
  </div>

  <!-- hidden file inputs -->
  <input
    bind:this={iconInputEl}
    type="file"
    accept="image/png,image/jpeg,image/svg+xml"
    style="display:none"
    onchange={onIconChange}
  />
  <input
    bind:this={mdInputEl}
    type="file"
    accept=".md,.markdown,text/markdown"
    style="display:none"
    onchange={onMdImport}
  />
</div>

<style>
  .slot-card {
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-4);
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    background: var(--color-bg);
  }
  .head {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }
  .preview {
    width: 48px;
    height: 48px;
    border-radius: var(--radius-md);
    border: 1px solid var(--color-border);
    background: var(--color-bg-elevated);
    display: grid;
    place-items: center;
    overflow: hidden;
    flex: none;
  }
  .preview img {
    width: 40px;
    height: 40px;
    object-fit: contain;
  }
  .head-char {
    font-size: 20px;
    font-weight: 700;
    color: var(--color-fg);
  }
  .head-empty {
    color: var(--color-fg-muted);
  }
  .slot-no {
    font-size: 12px;
    color: var(--color-fg-muted);
    letter-spacing: 0.05em;
  }
  label {
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 12px;
    color: var(--color-fg-muted);
  }
  .text-input,
  .body-input {
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: 6px 8px;
    background: var(--color-bg);
    font-size: 13px;
    color: var(--color-fg);
  }
  .body-input {
    font-family: var(--font-mono);
    resize: vertical;
    min-height: 80px;
  }
  .actions {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-wrap: wrap;
  }
  .spacer {
    flex: 1;
  }
  .ghost,
  .primary {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    padding: 5px 10px;
    border-radius: var(--radius-sm);
    cursor: pointer;
    border: 1px solid var(--color-border);
    background: var(--color-bg);
  }
  .ghost {
    color: var(--color-fg);
  }
  .ghost.danger {
    color: var(--color-error);
    border-color: #f0c4c4;
  }
  .primary {
    background: var(--color-accent);
    border-color: var(--color-accent);
    color: #fff;
    font-weight: 500;
  }
  .primary:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }
</style>

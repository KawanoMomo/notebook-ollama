<script lang="ts">
  import Modal from '../Modal.svelte';
  import { FileText } from '@lucide/svelte';

  interface Props {
    /** 編集対象。null = 新規作成。 */
    initial: { id?: string; title: string; body: string } | null;
    onClose: () => void;
    onSave: (title: string, body: string) => Promise<void>;
  }
  let { initial, onClose, onSave }: Props = $props();

  let title = $state(initial?.title ?? '');
  let body = $state(initial?.body ?? '');
  let saving = $state(false);
  let mdInputEl: HTMLInputElement | null = null;

  const canSave = $derived(
    !saving && title.trim() !== '' && body.trim() !== '',
  );

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
      onClose();
    } finally {
      saving = false;
    }
  }
</script>

<Modal title={initial?.id ? 'プロンプトを編集' : 'プロンプトを追加'} {onClose}>
  <div class="form">
    <label>
      タイトル
      <input
        type="text"
        bind:value={title}
        maxlength="100"
        placeholder="例: 翻訳 / 校正"
      />
    </label>
    <label>
      プロンプト本文
      <textarea
        bind:value={body}
        maxlength="10000"
        rows="6"
        placeholder="クリック時に送信される本文を入力"
      ></textarea>
    </label>
    <div class="actions">
      <button type="button" class="ghost" onclick={() => mdInputEl?.click()}>
        <FileText size="13" /> Markdown ファイルからインポート…
      </button>
      <div class="spacer"></div>
      <button type="button" class="ghost" onclick={onClose}>キャンセル</button>
      <button
        type="button"
        class="primary"
        disabled={!canSave}
        onclick={handleSave}
      >
        保存
      </button>
    </div>
    <input
      bind:this={mdInputEl}
      type="file"
      accept=".md,.markdown,text/markdown"
      style="display:none"
      onchange={onMdImport}
    />
  </div>
</Modal>

<style>
  .form {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    width: 480px;
    max-width: 100%;
  }
  label {
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 12px;
    color: var(--color-fg-muted);
  }
  input[type='text'],
  textarea {
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: 6px 8px;
    background: var(--color-bg);
    font-size: 13px;
    color: var(--color-fg);
  }
  textarea {
    font-family: var(--font-mono);
    resize: vertical;
    min-height: 120px;
  }
  .actions {
    display: flex;
    align-items: center;
    gap: var(--space-2);
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

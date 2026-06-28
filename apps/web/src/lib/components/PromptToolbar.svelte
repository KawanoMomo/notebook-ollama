<script lang="ts">
  import type { PromptsOut } from '$lib/api/types';
  import { Send } from '@lucide/svelte';

  interface Props {
    /** null = まだ load していない or 失敗 → degraded(描画なし)。 */
    prompts: PromptsOut | null;
    streaming: boolean;
    /** 0 = ソース未選択 → 全要素 disabled(ChatInput 0件警告と整合)。 */
    sourcesSelected: number;
    onSend: (text: string) => void;
  }
  let { prompts, streaming, sourcesSelected, onSend }: Props = $props();

  const disabled = $derived(streaming || sourcesSelected <= 0);

  // 未設定スロット = title または body が空。設計 §3.2。
  function isUsable(s: { title: string; body: string }): boolean {
    return s.title.trim() !== '' && s.body.trim() !== '';
  }

  const usableFixed = $derived(
    prompts ? prompts.fixed.filter(isUsable) : [],
  );
  const hasDropdown = $derived(
    prompts ? prompts.dropdown.length > 0 : false,
  );
  // ツールバー全体非描画: 固定 0 件 + プルダウン 0 件、または prompts なし。
  const hide = $derived(
    !prompts || (usableFixed.length === 0 && !hasDropdown),
  );

  let selectedDropdownId = $state('');

  function onFixedClick(body: string) {
    if (disabled) return;
    onSend(body);
  }

  function onIssue() {
    if (disabled || !selectedDropdownId || !prompts) return;
    const target = prompts.dropdown.find((d) => d.id === selectedDropdownId);
    if (!target) return;
    onSend(target.body);
    selectedDropdownId = ''; // 仕様: 発火後に選択をリセット
  }
</script>

{#if !hide && prompts}
  <div class="prompt-toolbar">
    {#each prompts.fixed as slot, i (i)}
      {#if isUsable(slot)}
        <button
          class="fixed-slot"
          {disabled}
          onclick={() => onFixedClick(slot.body)}
          aria-label={slot.title}
          title={slot.title}
        >
          {#if slot.icon_url}
            <img src={slot.icon_url} alt={slot.title} />
          {:else}
            <span class="head-char">{slot.title.slice(0, 1)}</span>
          {/if}
        </button>
      {/if}
    {/each}

    {#if hasDropdown}
      {#if usableFixed.length > 0}
        <div class="divider" aria-hidden="true"></div>
      {/if}
      <select
        class="dropdown"
        bind:value={selectedDropdownId}
        {disabled}
        aria-label="その他プロンプト"
      >
        <option value="">その他プロンプト ▾</option>
        {#each prompts.dropdown as d (d.id)}
          <option value={d.id}>{d.title}</option>
        {/each}
      </select>
      <button
        class="issue"
        onclick={onIssue}
        disabled={disabled || !selectedDropdownId}
        aria-label="発行"
      >
        <Send size="12" /> 発行
      </button>
    {/if}
  </div>
{/if}

<style>
  .prompt-toolbar {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border-bottom: 1px solid var(--color-border);
    background: var(--color-bg-elevated);
    flex-wrap: wrap;
  }
  .fixed-slot {
    width: 32px;
    height: 32px;
    border-radius: var(--radius-md);
    border: 1px solid var(--color-border);
    background: var(--color-bg);
    display: grid;
    place-items: center;
    cursor: pointer;
    overflow: hidden;
    padding: 0;
  }
  .fixed-slot:hover:not(:disabled) {
    border-color: var(--color-accent);
    color: var(--color-accent);
  }
  .fixed-slot:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .fixed-slot img {
    width: 28px;
    height: 28px;
    object-fit: contain;
    display: block;
  }
  .head-char {
    font-size: 14px;
    font-weight: 600;
    color: var(--color-fg);
  }
  .divider {
    width: 1px;
    height: 20px;
    background: var(--color-border);
  }
  .dropdown {
    flex: 1;
    min-width: 0;
    max-width: 240px;
    font-size: 13px;
    padding: 4px 8px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-bg);
  }
  .dropdown:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .issue {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 10px;
    border-radius: var(--radius-md);
    border: 1px solid var(--color-border);
    background: var(--color-bg);
    color: var(--color-fg);
    font-size: 12px;
    cursor: pointer;
  }
  .issue:hover:not(:disabled) {
    border-color: var(--color-accent);
    color: var(--color-accent);
  }
  .issue:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
</style>

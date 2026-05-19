<script lang="ts">
  import type { Message } from '$lib/api/types';
  import { renderMarkdown } from '$lib/utils/markdown';
  import { injectCitationBadges } from '$lib/utils/citations';

  interface Props {
    message: Message;
    onCitationClick: (n: number) => void;
  }
  let { message, onCitationClick }: Props = $props();

  let html = $derived(
    message.role === 'assistant'
      ? injectCitationBadges(renderMarkdown(message.content), message.citations)
      : renderMarkdown(message.content),
  );

  function onClick(e: MouseEvent) {
    const t = e.target;
    if (t instanceof HTMLElement && t.classList.contains('citation-badge')) {
      const n = Number(t.dataset.n);
      if (Number.isFinite(n)) onCitationClick(n);
    }
  }
</script>

<article class={`msg ${message.role}`} onclick={onClick} role="presentation">
  <div class="role">{message.role === 'user' ? 'あなた' : 'アシスタント'}</div>
  <div class="content">{@html html}</div>
  {#if message.citations.length > 0}
    <ol class="cites">
      {#each message.citations as c (c.n)}
        <li>
          <span class="num">[{c.n}]</span> {c.source_title}
          {#if c.location}<span class="loc">/ {c.location}</span>{/if}
        </li>
      {/each}
    </ol>
  {/if}
</article>

<style>
  .msg {
    padding: var(--space-4);
    border-bottom: 1px solid var(--color-border);
    line-height: 1.6;
  }
  .msg.user {
    background: var(--color-bg-sidebar);
  }
  .role {
    font-size: 11px;
    color: var(--color-fg-muted);
    margin-bottom: var(--space-2);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .content :global(h1),
  .content :global(h2),
  .content :global(h3) {
    margin-top: var(--space-3);
  }
  .content :global(p) {
    margin: 0 0 var(--space-2);
  }
  .content :global(pre) {
    background: var(--color-bg-elevated);
    padding: var(--space-3);
    border-radius: var(--radius-md);
    overflow-x: auto;
    font-family: var(--font-mono);
    font-size: 12px;
  }
  .content :global(code) {
    font-family: var(--font-mono);
    font-size: 0.9em;
  }
  .cites {
    margin: var(--space-3) 0 0;
    padding: 0;
    list-style: none;
    font-size: 12px;
    color: var(--color-fg-muted);
  }
  .cites li {
    margin-bottom: var(--space-1);
  }
  .num {
    font-weight: 600;
    color: var(--color-fg);
  }
  .loc {
    color: var(--color-fg-muted);
  }
</style>

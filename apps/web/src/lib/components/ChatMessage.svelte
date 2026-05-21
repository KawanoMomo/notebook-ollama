<script lang="ts">
  import type { Citation, Message } from '$lib/api/types';
  import { renderMarkdown } from '$lib/utils/markdown';
  import { injectCitationBadges } from '$lib/utils/citations';

  interface Props {
    message: Message;
    onCitationClick: (chunkId: string) => void;
  }
  let { message, onCitationClick }: Props = $props();

  let html = $derived(
    message.role === 'assistant'
      ? injectCitationBadges(renderMarkdown(message.content), message.citations)
      : renderMarkdown(message.content),
  );

  function citationByN(n: number): Citation | undefined {
    return message.citations.find((c) => c.n === n);
  }

  function onContentClick(e: MouseEvent) {
    const t = e.target;
    if (t instanceof HTMLElement && t.classList.contains('citation-badge')) {
      const n = Number(t.dataset.n);
      const c = Number.isFinite(n) ? citationByN(n) : undefined;
      if (c) onCitationClick(c.chunk_id);
    }
  }
</script>

<article class={`msg ${message.role}`}>
  <div class="role">{message.role === 'user' ? 'あなた' : 'アシスタント'}</div>
  <div class="content" onclick={onContentClick} role="presentation">{@html html}</div>
  {#if message.citations.length > 0}
    <div class="cites">
      <div class="cites-label">出典</div>
      <ul class="cards">
        {#each message.citations as c (c.n)}
          <li>
            <button class="card" onclick={() => onCitationClick(c.chunk_id)} type="button">
              <div class="card-head">
                <span class="num">{c.n}</span>
                <span class="title" title={c.source_title}>{c.source_title}</span>
                {#if c.location}<span class="loc">· {c.location}</span>{/if}
              </div>
              {#if c.snippet}
                <p class="snippet">{c.snippet}</p>
              {/if}
            </button>
          </li>
        {/each}
      </ul>
    </div>
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
    margin: var(--space-4) 0 0;
  }
  .cites-label {
    font-size: 10px;
    color: var(--color-fg-muted);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: var(--space-2);
  }
  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .card {
    display: block;
    width: 100%;
    text-align: left;
    padding: var(--space-3);
    background: var(--color-bg-elevated);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    cursor: pointer;
    font: inherit;
    color: inherit;
    transition: border-color 120ms, background 120ms, transform 80ms;
  }
  .card:hover {
    border-color: var(--color-accent);
    background: color-mix(in srgb, var(--color-accent) 4%, var(--color-bg-elevated));
  }
  .card:active {
    transform: translateY(1px);
  }
  .card-head {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: 12px;
  }
  .num {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: var(--color-citation-bg);
    border: 1px solid var(--color-citation-border);
    color: #6b5300;
    border-radius: 50%;
    width: 18px;
    height: 18px;
    font-size: 11px;
    font-weight: 600;
    flex-shrink: 0;
  }
  .title {
    font-weight: 600;
    color: var(--color-fg);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
    flex: 1;
  }
  .loc {
    color: var(--color-fg-muted);
    font-size: 11px;
    flex-shrink: 0;
  }
  .snippet {
    margin: var(--space-2) 0 0;
    font-size: 12px;
    line-height: 1.5;
    color: var(--color-fg-muted);
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
</style>

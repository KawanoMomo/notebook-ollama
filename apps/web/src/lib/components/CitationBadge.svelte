<script lang="ts">
  import type { Citation } from '$lib/api/types';

  interface Props {
    citation: Citation;
    onclick: () => void;
  }
  let { citation, onclick }: Props = $props();
</script>

<button class="badge" {onclick} title={`${citation.source_title} ${citation.location}`}>
  {citation.n}
</button>

<style>
  .badge {
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
    margin: 0 2px;
    cursor: pointer;
    vertical-align: middle;
  }
  .badge:hover {
    background: #ffe879;
  }
</style>

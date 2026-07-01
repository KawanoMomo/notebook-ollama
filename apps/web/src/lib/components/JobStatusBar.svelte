<script lang="ts">
  import Spinner from './Spinner.svelte';
  import type { ActiveJob } from '$lib/stores/currentNotebook.svelte';
  import type { ConvStep } from '$lib/stores/events.svelte';

  interface Props {
    jobs: Array<ActiveJob & { step?: ConvStep }>;
  }
  let { jobs }: Props = $props();
</script>

{#if jobs.length > 0}
  <div class="jobbar" role="status" aria-live="polite">
    {#each jobs as j (j.kind + ':' + j.sourceId)}
      <span class="job">
        <Spinner size={12} />
        <span class="label">
          {j.label}{#if j.step?.step_label}（{j.step.step_label}{#if j.step.progress > 0}
              {Math.round(j.step.progress * 100)}%{/if}）{/if}
        </span>
      </span>
    {/each}
  </div>
{/if}

<style>
  .jobbar {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-4);
    padding: 6px var(--space-5);
    background: var(--color-bg-elevated);
    border-bottom: 1px solid var(--color-border);
    font-size: 12px;
    color: var(--color-fg);
  }
  .job {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--color-accent);
  }
  .label {
    color: var(--color-fg);
  }
</style>

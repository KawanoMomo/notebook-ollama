<script lang="ts">
  import Spinner from './Spinner.svelte';
  import type { ActiveJob } from '$lib/stores/currentNotebook.svelte';
  import type { ConvStep } from '$lib/stores/events.svelte';

  interface Props {
    jobs: Array<ActiveJob & { step?: ConvStep; etaSeconds?: number | null }>;
  }
  let { jobs }: Props = $props();

  /** 残り時間目安。数時間規模になりうるので分/時間で丸める。 */
  function formatEta(seconds: number): string {
    if (seconds < 60) return '残り約1分未満';
    const mins = Math.round(seconds / 60);
    if (mins < 60) return `残り約${mins}分`;
    const hours = Math.floor(mins / 60);
    const rest = mins % 60;
    return rest === 0 ? `残り約${hours}時間` : `残り約${hours}時間${rest}分`;
  }
</script>

{#if jobs.length > 0}
  <div class="jobbar" role="status" aria-live="polite">
    {#each jobs as j (j.kind + ':' + j.sourceId)}
      <span class="job">
        <Spinner size={12} />
        <span class="label">
          {j.label}{#if j.step?.step_label}（{j.step.step_label}{#if j.step.progress > 0}
              {Math.round(j.step.progress * 100)}%{/if}）{/if}{#if j.etaSeconds != null}
            <span class="eta">{formatEta(j.etaSeconds)}</span>{/if}
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
  .eta {
    margin-left: 6px;
    color: var(--color-fg-muted, var(--color-fg));
    opacity: 0.75;
  }
</style>

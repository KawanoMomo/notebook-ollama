<script lang="ts">
  import { Check } from '@lucide/svelte';
  import Spinner from './Spinner.svelte';
  import { eventsStore } from '$lib/stores/events.svelte';

  interface Props {
    sourceId: string;
  }
  let { sourceId }: Props = $props();

  // Fixed ordered UI rows (mock SCREEN 3).
  const UI_STEPS = ['文字起こし', '話者分離', '名前予想', 'LLM補正', 'チャンク+埋め込み'];

  // Map the real pipeline `step` strings emitted by recording_pipeline.py onto UI row indices.
  // transcribe→0, diarize→1, name_infer→2, correct→3, chunk/embed→4. `done` completes all rows.
  const STEP_INDEX: Record<string, number> = {
    transcribe: 0,
    diarize: 1,
    name_infer: 2,
    correct: 3,
    chunk: 4,
    embed: 4,
    done: 5,
  };

  const conv = $derived(eventsStore.convStepFor(sourceId));
  const progress = $derived(conv ? Math.max(0, Math.min(1, conv.progress)) : 0);

  // Current UI-row index. No step info yet → treat first row as current (0).
  // Unknown step name → treat as in-progress without crashing (keep current index, default 0).
  const currentIndex = $derived.by(() => {
    if (!conv) return 0;
    const mapped = STEP_INDEX[conv.step];
    return mapped === undefined ? 0 : mapped;
  });

  function rowState(i: number): 'done' | 'cur' | 'todo' {
    if (i < currentIndex) return 'done';
    if (i === currentIndex) return 'cur';
    return 'todo';
  }
</script>

<div class="conv">
  <p class="ct">RAGソースに変換中(PC リソースを使用)</p>
  {#each UI_STEPS as label, i (label)}
    {@const state = rowState(i)}
    <div class="cstep {state}">
      <span class="cdot">
        {#if state === 'done'}
          <Check size="10" color="#fff" strokeWidth={3} />
        {:else if state === 'cur'}
          <Spinner size={11} />
        {/if}
      </span>
      <span class="clabel">{label}</span>
    </div>
  {/each}
  <div class="pbar"><i style="width:{progress * 100}%"></i></div>
</div>

<style>
  .conv {
    padding: 6px var(--space-3) var(--space-3) 34px;
    background: var(--color-bg-elevated);
    border-bottom: 1px solid var(--color-border);
  }
  .ct {
    font-size: 11px;
    color: var(--color-fg-muted);
    margin: 0 0 6px;
  }
  .cstep {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: 12px;
    padding: 3px 0;
  }
  .cstep.done {
    color: var(--color-success);
  }
  .cstep.cur {
    color: var(--color-fg);
    font-weight: 600;
  }
  .cstep.todo {
    color: var(--color-fg-muted);
  }
  .cdot {
    width: 15px;
    height: 15px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    font-size: 10px;
    flex: none;
    line-height: 0;
  }
  .cstep.done .cdot {
    background: var(--color-success);
    color: #fff;
  }
  .cstep.cur .cdot {
    color: var(--color-accent);
  }
  .cstep.todo .cdot {
    border: 2px solid var(--color-border);
  }
  .pbar {
    height: 6px;
    background: var(--color-border);
    border-radius: 999px;
    overflow: hidden;
    margin-top: var(--space-2);
  }
  .pbar i {
    display: block;
    height: 100%;
    background: var(--color-accent);
    border-radius: 999px;
    transition: width 0.3s ease;
  }
</style>

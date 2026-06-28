import { openNotebookEvents, type SourceStatusEvent } from "$lib/api/events";
import { currentNotebookStore } from "./currentNotebook.svelte";
import { notify } from "$lib/utils/notifications";

export interface ConvStep {
  step: string;
  step_label: string;
  progress: number;
}

export interface EventsStore {
  start(notebookId: string): void;
  stop(): void;
  convStepFor(sourceId: string): ConvStep | undefined;
}

export function createEventsStore(): EventsStore {
  let close: (() => void) | null = null;
  const lastStatus = new Map<string, string>();
  // Latest pipeline step per source_id, driven by SSE payloads that carry `step`.
  let convSteps = $state<Record<string, ConvStep>>({});

  return {
    convStepFor(sourceId) {
      return convSteps[sourceId];
    },
    start(notebookId) {
      close?.();
      lastStatus.clear();
      convSteps = {};
      close = openNotebookEvents(notebookId, (ev: SourceStatusEvent) => {
        // Record the latest pipeline step for this source (if the payload carries one).
        if (typeof ev.step === "string") {
          convSteps = {
            ...convSteps,
            [ev.source_id]: {
              step: ev.step,
              step_label: typeof ev.step_label === "string" ? ev.step_label : "",
              progress: typeof ev.progress === "number" ? ev.progress : 0,
            },
          };
        }
        // patch the source in currentNotebookStore
        const existing = currentNotebookStore.sources.find(
          (s) => s.id === ev.source_id,
        );
        if (!existing) return;
        const prev = lastStatus.get(ev.source_id) ?? existing.status;
        lastStatus.set(ev.source_id, ev.status);
        const chunkCount =
          typeof ev.chunk_count === "number" ? ev.chunk_count : existing.chunk_count;
        const embedded =
          typeof ev.embedded === "number" ? ev.embedded : undefined;
        currentNotebookStore.upsertSource({
          ...existing,
          status: ev.status as typeof existing.status,
          chunk_count: chunkCount,
          embedded,
        });
        if (prev !== ev.status) {
          const title = existing.title ?? existing.origin ?? "ソース";
          if (ev.status === "ready") {
            notify({
              title: "取り込み完了",
              body: title,
              tag: `source-ready-${ev.source_id}`,
            });
          } else if (ev.status === "error") {
            const errMsg = typeof ev.error_msg === "string" ? ev.error_msg : "";
            const detail = errMsg ? ` — ${errMsg}` : "";
            notify({
              title: "取り込み失敗",
              body: `${title}${detail}`,
              tag: `source-error-${ev.source_id}`,
            });
          }
        }
      });
    },
    stop() {
      close?.();
      lastStatus.clear();
      convSteps = {};
      close = null;
    },
  };
}

export const eventsStore = createEventsStore();

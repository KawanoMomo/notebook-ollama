import { openNotebookEvents, type SourceStatusEvent } from "$lib/api/events";
import type { Source } from "$lib/api/types";
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
          // 要約/ADRジョブの進行状態。ペイロードに含まれる場合のみ上書きし、
          // 含まれない従来イベント(取り込みパイプライン等)では既存値を維持する。
          ...(typeof ev.summary_status === 'string'
            ? { summary_status: ev.summary_status as Source['summary_status'] }
            : {}),
          ...(typeof ev.adr_status === 'string'
            ? { adr_status: ev.adr_status as Source['adr_status'] }
            : {}),
          // READY イベントは本文を同梱する(BE契約)。再取得なしで即時表示する。
          ...(typeof ev.summary === 'string' ? { summary: ev.summary } : {}),
          ...(typeof ev.adr_draft === 'string' ? { adr_draft: ev.adr_draft } : {}),
          ...(typeof ev.adr_template === 'string'
            ? { adr_template: ev.adr_template as Source['adr_template'] }
            : {}),
          ...(typeof ev.adr_confidence === 'string'
            ? { adr_confidence: ev.adr_confidence as Source['adr_confidence'] }
            : {}),
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

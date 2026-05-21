import { openNotebookEvents, type SourceStatusEvent } from "$lib/api/events";
import { currentNotebookStore } from "./currentNotebook.svelte";
import { notify } from "$lib/utils/notifications";

export interface EventsStore {
  start(notebookId: string): void;
  stop(): void;
}

export function createEventsStore(): EventsStore {
  let close: (() => void) | null = null;
  const lastStatus = new Map<string, string>();

  return {
    start(notebookId) {
      close?.();
      lastStatus.clear();
      close = openNotebookEvents(notebookId, (ev: SourceStatusEvent) => {
        // patch the source in currentNotebookStore
        const existing = currentNotebookStore.sources.find(
          (s) => s.id === ev.source_id,
        );
        if (!existing) return;
        const prev = lastStatus.get(ev.source_id) ?? existing.status;
        lastStatus.set(ev.source_id, ev.status);
        currentNotebookStore.upsertSource({
          ...existing,
          status: ev.status as typeof existing.status,
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
      close = null;
    },
  };
}

export const eventsStore = createEventsStore();

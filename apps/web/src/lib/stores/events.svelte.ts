import { openNotebookEvents, type SourceStatusEvent } from '$lib/api/events';
import { currentNotebookStore } from './currentNotebook.svelte';

export interface EventsStore {
  start(notebookId: string): void;
  stop(): void;
}

export function createEventsStore(): EventsStore {
  let close: (() => void) | null = null;

  return {
    start(notebookId) {
      close?.();
      close = openNotebookEvents(notebookId, (ev: SourceStatusEvent) => {
        // patch the source in currentNotebookStore
        const existing = currentNotebookStore.sources.find((s) => s.id === ev.source_id);
        if (!existing) return;
        currentNotebookStore.upsertSource({
          ...existing,
          status: ev.status as typeof existing.status,
        });
      });
    },
    stop() {
      close?.();
      close = null;
    },
  };
}

export const eventsStore = createEventsStore();

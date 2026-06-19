import type { Notebook, Source } from '$lib/api/types';
import { notebooksApi } from '$lib/api/notebooks';
import { sourcesApi } from '$lib/api/sources';

export interface CurrentNotebookStore {
  readonly notebook: Notebook | null;
  readonly sources: Source[];
  readonly selectedSourceIds: ReadonlySet<string>;
  readonly loading: boolean;
  readonly error: string | null;
  load(id: string): Promise<void>;
  update(patch: { default_model?: string | null }): Promise<void>;
  clear(): void;
  upsertSource(s: Source): void;
  removeSource(id: string): void;
  toggleSelected(id: string): void;
  clearSelection(): void;
}

export function createCurrentNotebookStore(
  nbApi = notebooksApi,
  srcApi = sourcesApi,
): CurrentNotebookStore {
  let notebook = $state<Notebook | null>(null);
  let sources = $state<Source[]>([]);
  let selected = $state<Set<string>>(new Set());
  let loading = $state(false);
  let error = $state<string | null>(null);

  return {
    get notebook() {
      return notebook;
    },
    get sources() {
      return sources;
    },
    get selectedSourceIds() {
      return selected;
    },
    get loading() {
      return loading;
    },
    get error() {
      return error;
    },
    async load(id) {
      loading = true;
      error = null;
      try {
        const [nb, ss] = await Promise.all([nbApi.get(id), srcApi.list(id)]);
        notebook = nb;
        sources = ss;
      } catch (e) {
        error = e instanceof Error ? e.message : String(e);
      } finally {
        loading = false;
      }
    },
    async update(patch) {
      if (!notebook) return;
      const id = notebook.id;
      const updated = await nbApi.update(id, patch);
      // load() で別ノートに切り替わっていない場合のみ反映
      if (notebook && notebook.id === id) {
        notebook = updated;
      }
    },
    clear() {
      notebook = null;
      sources = [];
      selected = new Set();
      error = null;
    },
    upsertSource(s) {
      const idx = sources.findIndex((x) => x.id === s.id);
      if (idx >= 0) {
        sources = sources.map((x) => (x.id === s.id ? s : x));
      } else {
        sources = [s, ...sources];
      }
    },
    removeSource(id) {
      sources = sources.filter((x) => x.id !== id);
      const next = new Set(selected);
      next.delete(id);
      selected = next;
    },
    toggleSelected(id) {
      const next = new Set(selected);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      selected = next;
    },
    clearSelection() {
      selected = new Set();
    },
  };
}

export const currentNotebookStore = createCurrentNotebookStore();

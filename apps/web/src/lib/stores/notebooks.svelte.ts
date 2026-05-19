import type { Notebook } from '$lib/api/types';
import { notebooksApi } from '$lib/api/notebooks';

export interface NotebooksStore {
  readonly items: Notebook[];
  readonly loading: boolean;
  readonly error: string | null;
  load(): Promise<void>;
  add(nb: Notebook): void;
  update(nb: Notebook): void;
  remove(id: string): void;
}

type Api = Pick<typeof notebooksApi, 'list'>;

export function createNotebooksStore(api: Api = notebooksApi): NotebooksStore {
  let items = $state<Notebook[]>([]);
  let loading = $state(false);
  let error = $state<string | null>(null);

  return {
    get items() {
      return items;
    },
    get loading() {
      return loading;
    },
    get error() {
      return error;
    },
    async load() {
      loading = true;
      error = null;
      try {
        items = await api.list();
      } catch (e) {
        error = e instanceof Error ? e.message : String(e);
      } finally {
        loading = false;
      }
    },
    add(nb) {
      items = [nb, ...items];
    },
    update(nb) {
      items = items.map((x) => (x.id === nb.id ? nb : x));
    },
    remove(id) {
      items = items.filter((x) => x.id !== id);
    },
  };
}

export const notebooksStore = createNotebooksStore();

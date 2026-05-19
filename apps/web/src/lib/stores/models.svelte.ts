import type { ModelInfo, NotebookDefault } from '$lib/api/types';
import { modelsApi } from '$lib/api/models';

export interface ModelsStore {
  readonly models: ModelInfo[];
  readonly defaults: NotebookDefault[];
  readonly loading: boolean;
  readonly error: string | null;
  load(): Promise<void>;
}

export function createModelsStore(api = modelsApi): ModelsStore {
  let models = $state<ModelInfo[]>([]);
  let defaults = $state<NotebookDefault[]>([]);
  let loading = $state(false);
  let error = $state<string | null>(null);

  return {
    get models() {
      return models;
    },
    get defaults() {
      return defaults;
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
        const out = await api.list();
        models = out.models;
        defaults = out.defaults_by_notebook;
      } catch (e) {
        error = e instanceof Error ? e.message : String(e);
      } finally {
        loading = false;
      }
    },
  };
}

export const modelsStore = createModelsStore();

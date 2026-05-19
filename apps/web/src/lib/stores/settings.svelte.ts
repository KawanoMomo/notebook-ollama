import type { AppSettings, Stats } from '$lib/api/types';
import { settingsApi } from '$lib/api/settings';

export interface SettingsStore {
  readonly settings: AppSettings | null;
  readonly stats: Stats | null;
  readonly loading: boolean;
  readonly error: string | null;
  load(): Promise<void>;
}

export function createSettingsStore(api = settingsApi): SettingsStore {
  let settings = $state<AppSettings | null>(null);
  let stats = $state<Stats | null>(null);
  let loading = $state(false);
  let error = $state<string | null>(null);

  return {
    get settings() {
      return settings;
    },
    get stats() {
      return stats;
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
        const [s, st] = await Promise.all([api.get(), api.stats()]);
        settings = s;
        stats = st;
      } catch (e) {
        error = e instanceof Error ? e.message : String(e);
      } finally {
        loading = false;
      }
    },
  };
}

export const settingsStore = createSettingsStore();

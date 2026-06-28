import type { DropdownPromptOut, PromptsOut } from '$lib/api/types';
import { promptsApi as defaultApi } from '$lib/api/prompts';

export interface PromptsStore {
  readonly prompts: PromptsOut | null;
  readonly loading: boolean;
  readonly error: string | null;

  load(): Promise<void>;
  saveFixed(slot: 0 | 1 | 2, title: string, body: string): Promise<void>;
  clearFixed(slot: 0 | 1 | 2): Promise<void>;
  uploadIcon(slot: 0 | 1 | 2, file: File): Promise<void>;
  deleteIcon(slot: 0 | 1 | 2): Promise<void>;

  addDropdown(title: string, body: string): Promise<DropdownPromptOut | null>;
  updateDropdown(id: string, title: string, body: string): Promise<void>;
  deleteDropdown(id: string): Promise<void>;
  moveDropdown(id: string, delta: -1 | 1): Promise<void>;
}

/**
 * 純粋関数: ids 配列上で `id` を delta 分だけ移動した新しい配列を返す。
 * 境界外(先頭で -1 / 末尾で +1)や未知 id では入力配列をそのまま返す。
 */
export function movePromptIds(
  ids: readonly string[],
  id: string,
  delta: -1 | 1,
): string[] {
  const idx = ids.indexOf(id);
  if (idx < 0) return [...ids];
  const target = idx + delta;
  if (target < 0 || target >= ids.length) return [...ids];
  const next = [...ids];
  const [moved] = next.splice(idx, 1);
  next.splice(target, 0, moved);
  return next;
}

export function createPromptsStore(api = defaultApi): PromptsStore {
  let prompts = $state<PromptsOut | null>(null);
  let loading = $state(false);
  let error = $state<string | null>(null);

  async function _safeWrap<T>(fn: () => Promise<T>): Promise<T | null> {
    try {
      const r = await fn();
      error = null;
      return r;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      return null;
    }
  }

  return {
    get prompts() {
      return prompts;
    },
    get loading() {
      return loading;
    },
    get error() {
      return error;
    },
    async load() {
      loading = true;
      try {
        const r = await api.get();
        prompts = r;
        error = null;
      } catch (e) {
        error = e instanceof Error ? e.message : String(e);
      } finally {
        loading = false;
      }
    },
    async saveFixed(slot, title, body) {
      const next = await _safeWrap(() => api.putFixed(slot, title, body));
      if (next) prompts = next;
    },
    async clearFixed(slot) {
      const next = await _safeWrap(() => api.deleteFixed(slot));
      if (next) prompts = next;
    },
    async uploadIcon(slot, file) {
      const next = await _safeWrap(() => api.uploadIcon(slot, file));
      if (next) prompts = next;
    },
    async deleteIcon(slot) {
      const next = await _safeWrap(() => api.deleteIcon(slot));
      if (next) prompts = next;
    },
    async addDropdown(title, body) {
      const created = await _safeWrap(() => api.addDropdown(title, body));
      if (created && prompts) {
        prompts = {
          ...prompts,
          dropdown: [...prompts.dropdown, created],
        };
      }
      return created;
    },
    async updateDropdown(id, title, body) {
      const updated = await _safeWrap(() => api.updateDropdown(id, title, body));
      if (updated && prompts) {
        prompts = {
          ...prompts,
          dropdown: prompts.dropdown.map((d) => (d.id === id ? updated : d)),
        };
      }
    },
    async deleteDropdown(id) {
      const r = await _safeWrap(async () => {
        await api.deleteDropdown(id);
        return true as const;
      });
      if (r && prompts) {
        prompts = {
          ...prompts,
          dropdown: prompts.dropdown.filter((d) => d.id !== id),
        };
      }
    },
    async moveDropdown(id, delta) {
      if (!prompts) return;
      const currentIds = prompts.dropdown.map((d) => d.id);
      const nextIds = movePromptIds(currentIds, id, delta);
      if (nextIds.join(',') === currentIds.join(',')) return; // no-op
      const next = await _safeWrap(() => api.reorderDropdown(nextIds));
      if (next) prompts = next;
    },
  };
}

export const promptsStore = createPromptsStore();

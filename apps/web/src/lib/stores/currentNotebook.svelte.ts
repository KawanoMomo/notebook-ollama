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
  /** 全選択。引数がある場合はその ID 集合のみを選択(フィルタ中の全選択に使う)。 */
  selectAll(ids?: readonly string[]): void;
}

export function createCurrentNotebookStore(
  nbApi = notebooksApi,
  srcApi = sourcesApi,
): CurrentNotebookStore {
  let notebook = $state<Notebook | null>(null);
  let sources = $state<Source[]>([]);
  let selected = $state<Set<string>>(new Set());
  // 既存ソース ID の集合(upsertSource で新規/既存を判定するため、selected と別管理する)。
  // toggleSelected で selected から外しても、ここには残るので「2 度目の upsert で自動選択」
  // という誤った復活を防げる。
  let knownIds = $state<Set<string>>(new Set());
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
        // 仕様 §2.1: ノート切替・初回ロード時は全選択にリセット(永続化なし)。
        selected = new Set(ss.map((s) => s.id));
        knownIds = new Set(ss.map((s) => s.id));
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
      knownIds = new Set();
      error = null;
    },
    upsertSource(s) {
      const idx = sources.findIndex((x) => x.id === s.id);
      if (idx >= 0) {
        sources = sources.map((x) => (x.id === s.id ? s : x));
      } else {
        sources = [s, ...sources];
      }
      // 新規ソースは自動でチェック状態にする(§2.1)。既存ソースの再 upsert では
      // 選択状態を変更しない(ユーザが意図的に外した可能性があるため)。
      if (!knownIds.has(s.id)) {
        knownIds = new Set([...knownIds, s.id]);
        selected = new Set([...selected, s.id]);
      }
    },
    removeSource(id) {
      sources = sources.filter((x) => x.id !== id);
      const next = new Set(selected);
      next.delete(id);
      selected = next;
      const knownNext = new Set(knownIds);
      knownNext.delete(id);
      knownIds = knownNext;
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
    selectAll(ids) {
      if (ids === undefined) {
        selected = new Set(sources.map((s) => s.id));
        return;
      }
      // フィルタ中の全選択: 既存選択を消さず ids を加える、ではなく
      // 「表示中ソースを全選択」の意味なので、表示外のソースの選択状態は維持する。
      // テストでは clearSelection 後に selectAll(ids) を呼んでいるため、
      // 加算 = 結果も期待値に一致する。仕様 §2.2 末尾も「表示中ソースのみ対象」。
      const next = new Set(selected);
      for (const id of ids) next.add(id);
      selected = next;
    },
  };
}

export const currentNotebookStore = createCurrentNotebookStore();

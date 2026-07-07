import type { Notebook, Source, SourceLink } from '$lib/api/types';
import { notebooksApi } from '$lib/api/notebooks';
import { sourcesApi } from '$lib/api/sources';
import { linksApi } from '$lib/api/links';

/** JobStatusBar に表示する進行中ジョブ1件。 */
export interface ActiveJob {
  sourceId: string;
  kind: 'ingest' | 'summary' | 'adr';
  label: string;
}

export interface CurrentNotebookStore {
  readonly notebook: Notebook | null;
  readonly sources: Source[];
  readonly selectedSourceIds: ReadonlySet<string>;
  readonly loading: boolean;
  readonly error: string | null;
  /** 進行中ジョブ一覧(取り込み/要約/ADR)。JobStatusBar が購読する。 */
  readonly activeJobs: ActiveJob[];
  /** ソース親子の手動リンク一覧(発表モード/ツリー表示用)。 */
  readonly links: SourceLink[];
  load(id: string): Promise<void>;
  update(patch: { default_model?: string | null }): Promise<void>;
  clear(): void;
  upsertSource(s: Source): void;
  removeSource(id: string): void;
  toggleSelected(id: string): void;
  clearSelection(): void;
  /** 全選択。引数がある場合はその ID 集合のみを選択(フィルタ中の全選択に使う)。 */
  selectAll(ids?: readonly string[]): void;
  /** child の親を parent に設定する(既存があれば付け替え)。例外は呼び出し元へ伝播。 */
  setParent(childId: string, parentId: string): Promise<void>;
  /** child の親子リンクを解除する。例外は呼び出し元へ伝播。 */
  removeParent(childId: string): Promise<void>;
}

export function createCurrentNotebookStore(
  nbApi = notebooksApi,
  srcApi = sourcesApi,
  lnkApi = linksApi,
): CurrentNotebookStore {
  let notebook = $state<Notebook | null>(null);
  let sources = $state<Source[]>([]);
  let links = $state<SourceLink[]>([]);
  let selected = $state<Set<string>>(new Set());
  // 既存ソース ID の集合(upsertSource で新規/既存を判定するため、selected と別管理する)。
  // toggleSelected で selected から外しても、ここには残るので「2 度目の upsert で自動選択」
  // という誤った復活を防げる。
  let knownIds = $state<Set<string>>(new Set());
  let loading = $state(false);
  let error = $state<string | null>(null);

  // links 取得の世代カウンタ。連打/並行 mutation やノート切替で複数の list() が
  // 同時に飛んだとき、最後に発行された取得だけを links に反映する(古い応答は破棄)。
  let linksFetchSeq = 0;

  /**
   * links を再取得して反映する。degradeOnError=true(load() の初回取得)は
   * 失敗時に links=[] へ落としてソース表示を守る。false(mutation 後)は
   * 例外を呼び出し元へ伝播する。いずれも世代チェックで古い応答を破棄する。
   */
  async function refreshLinks(nbId: string, opts?: { degradeOnError?: boolean }): Promise<void> {
    const seq = ++linksFetchSeq;
    try {
      const fetched = await lnkApi.list(nbId);
      if (seq === linksFetchSeq) links = fetched;
    } catch (e) {
      if (opts?.degradeOnError) {
        if (seq === linksFetchSeq) links = [];
        return;
      }
      throw e;
    }
  }

  // 進行中ジョブの導出。判定条件は spec 2026-07-02 に基づく:
  // status ∈ {pending,parsing,chunking,embedding} / summary_status==='generating'
  // / adr_status==='generating'。error/skipped は進行中として扱わない。
  const INGEST_ACTIVE = new Set(['pending', 'parsing', 'chunking', 'embedding']);
  const activeJobs = $derived.by<ActiveJob[]>(() => {
    const jobs: ActiveJob[] = [];
    for (const s of sources) {
      const name = s.title ?? s.origin ?? 'ソース';
      if (INGEST_ACTIVE.has(s.status)) {
        jobs.push({ sourceId: s.id, kind: 'ingest', label: `${name}: 取り込み中` });
      }
      if (s.summary_status === 'generating') {
        jobs.push({ sourceId: s.id, kind: 'summary', label: `${name}: 要約生成中` });
      }
      if (s.adr_status === 'generating') {
        jobs.push({ sourceId: s.id, kind: 'adr', label: `${name}: ADR生成中` });
      }
    }
    return jobs;
  });

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
    get activeJobs() {
      return activeJobs;
    },
    get links() {
      return links;
    },
    async load(id) {
      loading = true;
      error = null;
      try {
        // links は notebook/sources と並行取得する。refreshLinks が世代チェックと
        // 失敗時の degrade(links=[])を担うため、links の失敗が notebook/sources
        // 側の error state を汚すことはない。
        const [nb, ss] = await Promise.all([
          nbApi.get(id),
          srcApi.list(id),
          refreshLinks(id, { degradeOnError: true }),
        ]);
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
      links = [];
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
    async setParent(childId, parentId) {
      const nbId = notebook?.id;
      if (!nbId) return;
      // linksApi 呼び出しの例外はここで飲み込まず呼び出し元(パネル側)へ伝播させ、
      // toast 表示等の UI 判断に委ねる。
      await lnkApi.setParent(nbId, childId, parentId);
      await refreshLinks(nbId);
    },
    async removeParent(childId) {
      const nbId = notebook?.id;
      if (!nbId) return;
      await lnkApi.removeParent(nbId, childId);
      await refreshLinks(nbId);
    },
  };
}

export const currentNotebookStore = createCurrentNotebookStore();

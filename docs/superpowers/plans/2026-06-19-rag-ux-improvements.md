# RAG運用UX改善(群1) 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox-style TDD (失敗テスト→fail確認→最小実装→pass確認→commit). GUI変更は各機能末尾の Playwright 実機スクショ検証をゲートにする(自動テストGREENのみでのPASS禁止)。

**Goal:** 録音→RAG機能の体感品質を低リスクに底上げする5機能を実装する: #4 設定戻る / #6 取得スコープ化 / #7 ソース全文ビュー / #5 録音再生成 / #8 チャット待機UX。

**Architecture:** FastAPI(`apps/api/`)+ 純ドメイン(`core/`)+ SvelteKit(Svelte 5 runes, `apps/web/`)。SQLite メタデータ + Qdrant(ローカル, dim=1024 bge-m3)+ Ollama。設計仕様は `docs/specs/2026-06-19-rag-ux-improvements-design.md`(決定は確定。逸脱しない)。

**Tech Stack:** Python(uv / pytest / ruff)、TypeScript + Svelte 5 runes(svelte-check / vitest / vite build)、sse-starlette(SSE)、qdrant-client、httpx。

**ブランチ:** `feature/rag-ux-improvements`(`feature/recording-source` の上に積む。master 直接編集禁止)。本プランはこのブランチ上で実行する。

## Global Constraints

これらは全タスクに暗黙で適用される(仕様の拘束要件):
- **新規ランタイム依存を追加しない**。既存コンポーネント(`Spinner` / `AudioCitationPlayer` / 設定永続化パターン / `RefreshCw` 等)を流用する。
- **既存テスト(202件)を壊さない**。`uv run pytest` 緑、`cd apps/web && npm run check` は **0 errors**(既存の6 warnings のみ許容、新規警告を増やさない)、`npm run build` 成功。
- **#6 後方互換:** `source_ids` 未指定/空 = 全件(現状挙動を維持)。Qdrant フィルタは既存 `notebook_id` の `must` に追加する形。MCP ツール(`core/mcp/tools/*`)は本プラン対象外(据置)。
- **#5:** 0チャンク録音の `status` は `ready` のまま変えない。再生成は **圧縮音源(.m4a/.opus/.mp3)から再STT**(WAV は削除済み)。音源の無い録音はボタン非表示(`has_audio`)。
- **#7:** 文書 = 元ファイルを再パースして忠実表示(既存 `core/ingestion/parsers` を再利用、再発明しない)。録音 = `ord` 順チャンクのトランスクリプト(話者+タイムコード、共有プレーヤー1個+行クリックでシーク)。既存の単一チャンク引用経路は不変。
- **#8 後方互換:** SSE に `ping` イベントを追加(既存クライアントは未知イベントを無視するので安全)。`chat_stream` に有限の read タイムアウトを付与(設定可、既定 120s)。Stop は既存 `conversationStore.cancel()` を UI 接続。
- **コミット:** 慣習的メッセージ(日本語可)。**`Co-Authored-By` trailer は付けない**。
- **GUI 検証:** 各機能の最終ステップで Playwright 実機スクショ検証(コントローラ実施)。

## ファイル構成(作成/変更マップ)

| 機能 | 主な作成 | 主な変更 |
|---|---|---|
| #4 設定戻る | `apps/web/src/lib/stores/navMemory.svelte.ts`(+test) | `apps/web/src/routes/+layout.svelte`(afterNavigate)、`apps/web/src/routes/settings/+page.svelte`(戻る矢印) |
| #6 スコープ化 | (なし) | `core/storage/vector_store.py`(Qdrant MatchAny)、`core/retrieval/search.py`、`core/generation/stream.py`(+Protocol)、`apps/api/schemas/chat.py`(MessageInput.source_ids)、`apps/api/routers/chat.py`、`apps/web/src/lib/api/chat.ts`、`.../stores/conversation.svelte.ts`、`.../components/ChatPanel.svelte` |
| #7 全文ビュー | (endpoint+repo追加) | `core/storage/chunks_repo.py`(list_chunks_for_source)、`apps/api/routers/sources.py`(GET content)、`apps/web/src/lib/components/SourceViewer.svelte`、`.../api/source_outline.ts`、`AudioCitationPlayer` の一般化 |
| #5 録音再生成 | (endpoint追加) | `apps/api/routers/recordings.py`(POST retry)、`apps/api/schemas/source.py`+`apps/api/routers/sources.py`(has_audio)、`apps/web/src/lib/components/SourceCard.svelte`/`SourcesPanel.svelte`、`.../api/sources.ts`、`.../api/types.ts` |
| #8 チャット待機 | (vitest test追加) | `apps/web/src/lib/components/MessageList.svelte`(待機表示)、`ChatInput.svelte`(送信/Stop)、`ChatPanel.svelte`、`.../stores/conversation.svelte.ts`(ping/lastBeatAt/cancel)、`.../api/chat.ts`(ping)、`apps/api/routers/chat.py`(heartbeat)、`core/generation/stream.py`、`core/ollama/client.py`(read timeout)、`core/config.py`(OllamaSettings timeout) |

## 実装順(スプリント)

独立性が高いので、低リスク→重い順に: **#4 → #6 → #8 → #5 → #7**。各機能内のタスクは記載順に実行する。

---

## #4 設定の戻るボタン（元の画面へ戻る）

> 確定仕様: 設定見出し横に `ArrowLeft`+`goto` の戻る矢印（ノートブック詳細トップバーと同パターン）。戻り先は「直前に居た画面」（最後のルートを記憶、無ければ `/`）。未保存ドラフトの離脱ガードは無し。
>
> 採用方式（1行justify）: `$lib/stores/navMemory.svelte.ts` に「設定以外の最後のパス」を保持し、レイアウトの `afterNavigate` で更新する。これが最も単純かつ堅牢 — クライアント遷移で消えず、全ての歯車リンクへ `?from=` を付ける必要もなく、`document.referrer`（SPA内部遷移では空になる）と違ってピュアロジックとして単体テスト可能。

---

### Task A.1 — nav-memory ストア（直前の非設定ルートを記憶）

純ロジックの Svelte runes ストア。`notebooks.test.ts` と同じ vitest 慣習で**実テスト**を回す。

**Files**
- Create: `apps/web/src/lib/stores/navMemory.svelte.ts`
- Test: `apps/web/tests/unit/stores/navMemory.test.ts`

**Interfaces**
- Produces:
  - `interface NavMemoryStore { readonly lastPath: string; record(path: string): void; }`
  - `function createNavMemoryStore(): NavMemoryStore`
  - `const navMemoryStore: NavMemoryStore`（シングルトン）
- 振る舞い: `record(path)` は `path` が `/settings` で始まる場合は**無視**（設定→設定の自己参照を防ぐ）。それ以外は `lastPath` を更新。初期値 `'/'`。

**Steps**

1. 失敗するテストを書く。`apps/web/tests/unit/stores/navMemory.test.ts` を新規作成:
   ```ts
   import { describe, expect, it } from 'vitest';
   import { createNavMemoryStore } from '$lib/stores/navMemory.svelte';

   describe('navMemory store', () => {
     it('defaults lastPath to "/"', () => {
       const store = createNavMemoryStore();
       expect(store.lastPath).toBe('/');
     });

     it('records a non-settings path', () => {
       const store = createNavMemoryStore();
       store.record('/notebooks/abc');
       expect(store.lastPath).toBe('/notebooks/abc');
     });

     it('ignores settings paths (keeps previous)', () => {
       const store = createNavMemoryStore();
       store.record('/notebooks/abc');
       store.record('/settings');
       expect(store.lastPath).toBe('/notebooks/abc');
     });

     it('keeps default when only settings visited', () => {
       const store = createNavMemoryStore();
       store.record('/settings');
       expect(store.lastPath).toBe('/');
     });
   });
   ```

2. テストを実行して**失敗を確認**する（モジュール未作成で import 解決エラー）:
   ```
   cd apps/web && npx vitest run tests/unit/stores/navMemory.test.ts
   ```
   期待される失敗: `Failed to load url $lib/stores/navMemory.svelte ... Does the file exist?`（4 件とも実行不能）。

3. 最小実装を書く。`apps/web/src/lib/stores/navMemory.svelte.ts` を新規作成:
   ```ts
   export interface NavMemoryStore {
     readonly lastPath: string;
     record(path: string): void;
   }

   export function createNavMemoryStore(): NavMemoryStore {
     let lastPath = $state('/');

     return {
       get lastPath() {
         return lastPath;
       },
       record(path: string) {
         // 設定ページ自身は記録しない（設定→設定の自己参照／無限ループを防ぐ）。
         if (path.startsWith('/settings')) return;
         lastPath = path;
       },
     };
   }

   export const navMemoryStore = createNavMemoryStore();
   ```

4. テストを再実行して**合格を確認**する:
   ```
   cd apps/web && npx vitest run tests/unit/stores/navMemory.test.ts
   ```
   期待: `4 passed`。

5. コミットする:
   ```
   git add apps/web/src/lib/stores/navMemory.svelte.ts apps/web/tests/unit/stores/navMemory.test.ts
   git commit -m "feat(web): 直前の非設定ルートを記憶する navMemory ストアを追加"
   ```

---

### Task A.2 — 直前ルートの記録（レイアウトの afterNavigate）

`navMemoryStore.record` をレイアウトの `afterNavigate` フックに接続し、設定へ入る**前**のルートを必ず保持する。純UI配線なので `npm run check` + `build` がゲート。

**Files**
- Modify: `apps/web/src/routes/+layout.svelte`

**Interfaces**
- Consumes: `navMemoryStore.record(path: string)`（Task A.1）, `afterNavigate` from `$app/navigation`
- Produces: 各クライアント遷移完了時に `navMemoryStore.lastPath` が「直前の非設定パス」へ更新される副作用

**Steps**

1. `+layout.svelte` の import 群に `afterNavigate` と `navMemoryStore` を追加する。`bindShortcuts` の import 行（現状 7 行目）の直後に挿入:
   ```svelte
     import { bindShortcuts } from '$lib/utils/keys';
     import { afterNavigate } from '$app/navigation';
     import { navMemoryStore } from '$lib/stores/navMemory.svelte';
   ```

2. `afterNavigate` フックを `<script>` 内に追加する。`onDestroy(() => unbind?.());`（現状 21 行目）の直後に挿入:
   ```svelte
     onDestroy(() => unbind?.());

     // 各遷移完了時に「設定以外」の現在パスを記録し、設定からの戻り先にする。
     afterNavigate((nav) => {
       const path = nav.to?.url.pathname;
       if (path) navMemoryStore.record(path);
     });
   ```

3. 型チェックを実行して**0 エラー**を確認する:
   ```
   cd apps/web && npm run check
   ```
   期待: `svelte-check found 0 errors and 0 warnings`。

4. コミットする:
   ```
   git add apps/web/src/routes/+layout.svelte
   git commit -m "feat(web): afterNavigate で直前ルートを navMemory に記録"
   ```

---

### Task A.3 — 設定ページに戻る矢印を追加（元の画面へ goto）

`<h1>設定</h1>` をノートブック詳細と同じ `.topbar` で包み、`ArrowLeft` の戻るボタンを置く。`goBack()` は `navMemoryStore.lastPath`（無ければ `'/'`）へ `goto`。純UIなので `npm run check` + `build` + Playwright 実機スクショがゲート。

**Files**
- Modify: `apps/web/src/routes/settings/+page.svelte`

**Interfaces**
- Consumes: `goto` from `$app/navigation`, `ArrowLeft` from `@lucide/svelte`, `navMemoryStore.lastPath`（Task A.1）
- Produces: 設定見出し横の戻るボタン（`aria-label="戻る"`）押下で `navMemoryStore.lastPath` へ遷移する UI

**Steps**

1. import を追加する。`+page.svelte` 先頭、`import { onMount } from 'svelte';`（現状 2 行目）の直後に挿入:
   ```svelte
     import { onMount } from 'svelte';
     import { goto } from '$app/navigation';
     import { ArrowLeft } from '@lucide/svelte';
     import { navMemoryStore } from '$lib/stores/navMemory.svelte';
   ```

2. `goBack` 関数を `<script>` 内に追加する。`onMount(...)` ブロック（現状 11-14 行目）の直後、`</script>` の直前に挿入:
   ```svelte
     onMount(() => {
       settingsStore.load();
       modelsStore.load();
     });

     function goBack() {
       goto(navMemoryStore.lastPath || '/');
     }
   ```

3. 見出しをトップバーで置き換える。現状の `<h1>設定</h1>`（18 行目）を以下に差し替える:
   ```svelte
     <div class="topbar">
       <button class="back" onclick={goBack} aria-label="戻る">
         <ArrowLeft size="16" />
       </button>
       <h1>設定</h1>
     </div>
   ```

4. トップバー用 CSS を追加する。`<style>` 内、`h1 { ... }` ブロック（現状 172-175 行目）の**直後**に、ノートブック詳細の `.topbar`/`.back` を流用して挿入。`h1` の `margin` はトップバー内整列のため上書きする:
   ```svelte
     h1 {
       margin: 0 0 var(--space-4);
       font-size: 20px;
     }

     .topbar {
       display: flex;
       align-items: center;
       gap: var(--space-3);
       margin: 0 0 var(--space-4);
     }
     .topbar h1 {
       margin: 0;
     }
     .back {
       background: none;
       border: none;
       color: var(--color-fg-muted);
       padding: var(--space-1);
       border-radius: var(--radius-sm);
       display: inline-flex;
       cursor: pointer;
     }
     .back:hover {
       background: var(--color-bg-elevated);
       color: var(--color-fg);
     }
   ```

5. 型チェックを実行して**0 エラー**を確認する:
   ```
   cd apps/web && npm run check
   ```
   期待: `svelte-check found 0 errors and 0 warnings`。

6. プロダクションビルドが通ることを確認する:
   ```
   cd apps/web && npm run build
   ```
   期待: エラーなく `apps/web/dist/` へ出力。

7. **Playwright 実機スクショ検証ゲート（controller 実行）**: dev サーバ起動 → ノートブック詳細（`/notebooks/<id>`）→ ヘッダ歯車で `/settings` へ → (a) 設定見出し横に戻る矢印が表示されること、(b) 戻る矢印クリックで**直前のノートブック詳細**に戻ること、(c) `/settings` を**直リンク/リロード**で開いた場合は戻る矢印で `/`（ホーム）へ行くこと、をスクショで確認。GUI 変更につき自動テスト GREEN のみでの PASS は禁止（CLAUDE.md 視覚検証ゲート）。

8. コミットする:
   ```
   git add apps/web/src/routes/settings/+page.svelte
   git commit -m "feat(web): 設定ページに戻る矢印を追加し元の画面へ復帰"
   ```

---

参照ファイル（実装時の正本）:
- 戻りボタンの見た目/CSS 流用元: `E:\00_Git\10_NotebookOllama\apps\web\src\routes\notebooks\[id]\+page.svelte`（`.topbar`/`.back`/`ArrowLeft`+`goto`、L66-72 / L124-147）
- 改修対象の設定ページ: `E:\00_Git\10_NotebookOllama\apps\web\src\routes\settings\+page.svelte`
- 記録フックを足すレイアウト: `E:\00_Git\10_NotebookOllama\apps\web\src\routes\+layout.svelte`
- 歯車リンクの入口（今回は改修不要、`?from=` 方式不採用のため）: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\AppHeader.svelte`

---

## #6 Retrieval source-scoping (取得スコープ化 / チェック済みソースのみ検索)

> Spec: `docs/specs/2026-06-19-rag-ux-improvements-design.md` §2 (#6) + §3「#6 取得スコープ化」. Decisions are FIXED: `source_ids` allowlist threaded through every layer; empty/None = unfiltered (現状維持); selection is per-request ephemeral; web chat only; MCP tools (`core/mcp/tools/ask.py`, `find_quotes.py`) intentionally out of scope.
>
> Implementation direction is bottom-up (vector store → retrieval → generation → API schema → API router → frontend client → store → component), so each Task's deliverable is exercisable by the next.
>
> Branch: `feature/rag-ux-improvements` (master 直接編集禁止). Run `uv run pytest` from repo root; frontend commands from `apps/web/`.

---

### Task F.1 — VectorStore.search / delete_by_source: source_id allowlist filter

**Files**
- Modify: `core/storage/vector_store.py`
- Test: `tests/integration/test_vector_store.py` (add new test functions)

**Interfaces**
- Produces: `VectorStore.search(*, query: list[float], notebook_id: str, limit: int, source_ids: list[str] | None = None) -> list[SearchHit]` — when `source_ids` non-empty, appends `qm.FieldCondition(key="source_id", match=qm.MatchAny(any=source_ids))` to the existing `must=[notebook_id]`; empty/None ⇒ unchanged (notebook-only filter).
- Consumes (existing): payload already carries `"source_id"` (see `upsert`, L84); `qm.MatchAny` from `qdrant_client.http.models`.

**Steps**

1. Write the failing test. Append to `tests/integration/test_vector_store.py`:

```python
@pytest.mark.qdrant
def test_search_filters_by_source_ids(tmp_path):
    vs = VectorStore(path=tmp_path / "qdrant", dim=4)
    vs.ensure_collection()
    vs.upsert(
        [
            ChunkVector(
                id="a" * 26,
                vector=[1, 0, 0, 0],
                notebook_id="NB",
                source_id="SRC_A",
                source_kind="md",
                page=None,
                heading_path=None,
                ord=0,
            ),
            ChunkVector(
                id="b" * 26,
                vector=[1, 0, 0, 0],
                notebook_id="NB",
                source_id="SRC_B",
                source_kind="md",
                page=None,
                heading_path=None,
                ord=0,
            ),
        ]
    )
    # allowlist -> only SRC_A
    only_a = vs.search(query=[1, 0, 0, 0], notebook_id="NB", limit=10, source_ids=["SRC_A"])
    assert {h.source_id for h in only_a} == {"SRC_A"}
    # multi-value allowlist -> both
    both = vs.search(
        query=[1, 0, 0, 0], notebook_id="NB", limit=10, source_ids=["SRC_A", "SRC_B"]
    )
    assert {h.source_id for h in both} == {"SRC_A", "SRC_B"}
    # empty list -> unfiltered (both)
    empty = vs.search(query=[1, 0, 0, 0], notebook_id="NB", limit=10, source_ids=[])
    assert {h.source_id for h in empty} == {"SRC_A", "SRC_B"}
    # None (default) -> unfiltered (both), backward-compat
    default = vs.search(query=[1, 0, 0, 0], notebook_id="NB", limit=10)
    assert {h.source_id for h in default} == {"SRC_A", "SRC_B"}
```

2. Run it to see it fail:

```
uv run pytest tests/integration/test_vector_store.py::test_search_filters_by_source_ids -m qdrant
```

Expected failure: `TypeError: VectorStore.search() got an unexpected keyword argument 'source_ids'`.

3. Minimal implementation — edit `VectorStore.search` in `core/storage/vector_store.py`. Replace the current signature + `query_points` call (L97-111):

```python
    def search(
        self,
        *,
        query: list[float],
        notebook_id: str,
        limit: int,
        source_ids: list[str] | None = None,
    ) -> list[SearchHit]:
        must: list[qm.Condition] = [
            qm.FieldCondition(key="notebook_id", match=qm.MatchValue(value=notebook_id))
        ]
        if source_ids:
            must.append(
                qm.FieldCondition(key="source_id", match=qm.MatchAny(any=source_ids))
            )
        result = self._client.query_points(
            collection_name=COLLECTION,
            query=query,
            query_filter=qm.Filter(must=must),
            limit=limit,
        )
```

4. Run to pass:

```
uv run pytest tests/integration/test_vector_store.py -m qdrant
```

Expected: all `test_vector_store.py` tests pass (new test + 3 existing unchanged).

5. Commit:

```
git add core/storage/vector_store.py tests/integration/test_vector_store.py
git commit -m "feat(vector_store): search に source_ids allowlist フィルタを追加 (#6)"
```

---

### Task F.2 — RetrievalService.search: pass source_ids through

**Files**
- Modify: `core/retrieval/search.py`
- Test: `tests/integration/test_search.py` (add new test function)

**Interfaces**
- Produces: `RetrievalService.search(*, notebook_id: str, query: str, limit: int, source_ids: list[str] | None = None) -> list[RetrievedChunk]` — forwards `source_ids` verbatim to `self._vs.search(...)`.
- Consumes: `VectorStore.search(..., source_ids=...)` from Task F.1.

**Steps**

1. Write the failing test. Append to `tests/integration/test_search.py`:

```python
@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_retrieval_scopes_to_source_ids(tmp_path):
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    src_a = create_source(conn, notebook_id=nb.id, kind="md", title="A", content_hash="ha")
    src_b = create_source(conn, notebook_id=nb.id, kind="md", title="B", content_hash="hb")
    insert_chunks(
        conn,
        [
            ChunkRecord(
                id="a" * 26,
                source_id=src_a.id,
                notebook_id=nb.id,
                ord=0,
                page=None,
                heading_path=None,
                text="only in A",
                token_count=3,
            ),
            ChunkRecord(
                id="b" * 26,
                source_id=src_b.id,
                notebook_id=nb.id,
                ord=0,
                page=None,
                heading_path=None,
                text="only in B",
                token_count=3,
            ),
        ],
    )
    vs = VectorStore(path=tmp_path / "q", dim=4)
    vs.ensure_collection()
    vs.upsert(
        [
            ChunkVector(
                id="a" * 26,
                vector=[1, 0, 0, 0],
                notebook_id=nb.id,
                source_id=src_a.id,
                source_kind="md",
                page=None,
                heading_path=None,
                ord=0,
            ),
            ChunkVector(
                id="b" * 26,
                vector=[1, 0, 0, 0],
                notebook_id=nb.id,
                source_id=src_b.id,
                source_kind="md",
                page=None,
                heading_path=None,
                ord=0,
            ),
        ]
    )

    svc = RetrievalService(
        conn=conn, vector_store=vs, ollama=FakeGateway(), embedding_model="bge-m3"
    )
    scoped = await svc.search(notebook_id=nb.id, query="hi", limit=10, source_ids=[src_a.id])
    assert {h.source_id for h in scoped} == {src_a.id}
    unscoped = await svc.search(notebook_id=nb.id, query="hi", limit=10)
    assert {h.source_id for h in unscoped} == {src_a.id, src_b.id}
```

2. Run it to see it fail:

```
uv run pytest tests/integration/test_search.py::test_retrieval_scopes_to_source_ids -m qdrant
```

Expected failure: `TypeError: RetrievalService.search() got an unexpected keyword argument 'source_ids'`.

3. Minimal implementation — edit `core/retrieval/search.py`. Change the `search` signature (L48-53) and the `self._vs.search(...)` call (L58):

```python
    async def search(
        self,
        *,
        notebook_id: str,
        query: str,
        limit: int,
        source_ids: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        if not query.strip():
            return []
        qvec = await self._ollama.embed(model=self._embedding_model, text=query)
        hits = self._vs.search(
            query=qvec, notebook_id=notebook_id, limit=limit, source_ids=source_ids
        )
```

4. Run to pass:

```
uv run pytest tests/integration/test_search.py -m qdrant
```

Expected: both new test and existing `test_retrieval_returns_joined_chunks` pass.

5. Commit:

```
git add core/retrieval/search.py tests/integration/test_search.py
git commit -m "feat(retrieval): search に source_ids を透過配線 (#6)"
```

---

### Task F.3 — GenerationService.run + _RetrievalLike Protocol: forward source_ids

**Files**
- Modify: `core/generation/stream.py`
- Test: `tests/integration/test_generation.py` (add new test function)

**Interfaces**
- Produces: `GenerationService.run(..., source_ids: list[str] | None = None, ...)` — forwards to `self._deps.retrieval.search(..., source_ids=source_ids)`.
- Produces: `_RetrievalLike.search(self, *, notebook_id, query, limit, source_ids) -> list[RetrievedChunk]` (Protocol gains `source_ids`).
- Consumes: `RetrievalService.search(..., source_ids=...)` from Task F.2.

**Steps**

1. Write the failing test. This uses a fake retrieval that records the `source_ids` it received, proving the wiring. Append to `tests/integration/test_generation.py`:

```python
class RecordingRetrieval:
    def __init__(self):
        self.received_source_ids = "UNSET"

    async def search(self, *, notebook_id, query, limit, source_ids=None):
        self.received_source_ids = source_ids
        return [
            RetrievedChunk(
                chunk_id="c1",
                source_id="s1",
                source_title="ARM",
                source_kind="pdf",
                page=42,
                heading_path="§3",
                ord=0,
                text="Cortex content [...]",
                token_count=10,
                score=0.9,
            ),
        ]


@pytest.mark.asyncio
async def test_generation_forwards_source_ids_to_retrieval():
    retrieval = RecordingRetrieval()
    svc = GenerationService(deps=GenerationDeps(retrieval=retrieval, ollama=FakeGateway()))
    async for _ in svc.run(
        notebook_id="nb",
        model="qwen2.5:14b",
        question="質問",
        history=[],
        num_ctx=8192,
        context_budget_ratio=0.8,
        response_budget_tokens=1024,
        retrieval_top_k=8,
        min_history_turns=1,
        source_ids=["SRC_X"],
    ):
        pass
    assert retrieval.received_source_ids == ["SRC_X"]
```

2. Run it to see it fail:

```
uv run pytest tests/integration/test_generation.py::test_generation_forwards_source_ids_to_retrieval
```

Expected failure: `TypeError: GenerationService.run() got an unexpected keyword argument 'source_ids'`.

3. Minimal implementation — edit `core/generation/stream.py`. First update the `_RetrievalLike` Protocol (L24-25):

```python
class _RetrievalLike(Protocol):
    async def search(
        self,
        *,
        notebook_id: str,
        query: str,
        limit: int,
        source_ids: list[str] | None = None,
    ) -> list[RetrievedChunk]: ...
```

4. Now add the `run` parameter and forward it. Change the `run` signature (insert `source_ids` after `min_history_turns`, L50-62) and the retrieval call (L63-67):

```python
    async def run(
        self,
        *,
        notebook_id: str,
        model: str,
        question: str,
        history: list[HistoryTurn],
        num_ctx: int,
        context_budget_ratio: float,
        response_budget_tokens: int,
        retrieval_top_k: int,
        min_history_turns: int,
        source_ids: list[str] | None = None,
    ) -> AsyncIterator[GenerationEvent]:
        hits = await self._deps.retrieval.search(
            notebook_id=notebook_id,
            query=question,
            limit=retrieval_top_k,
            source_ids=source_ids,
        )
```

5. Run to pass:

```
uv run pytest tests/integration/test_generation.py
```

Expected: new forwarding test passes; existing `test_generation_emits_retrieval_then_tokens_then_done` still passes (its `FakeRetrieval.search` ignores the new kwarg via `**`-free signature? — note: that fake uses `async def search(self, *, notebook_id, query, limit)`; since `run` now always passes `source_ids=None`, that fake would break). Fix the existing fake in the same file:

In `tests/integration/test_generation.py`, change `FakeRetrieval.search` signature (L8) from:

```python
    async def search(self, *, notebook_id, query, limit):
```

to:

```python
    async def search(self, *, notebook_id, query, limit, source_ids=None):
```

6. Re-run to confirm both pass:

```
uv run pytest tests/integration/test_generation.py
```

Expected: 2 passed.

7. Commit:

```
git add core/generation/stream.py tests/integration/test_generation.py
git commit -m "feat(generation): run と _RetrievalLike に source_ids を配線 (#6)"
```

---

### Task F.4 — MessageInput schema: add source_ids field

**Files**
- Modify: `apps/api/schemas/chat.py`
- Test: `tests/unit/test_schemas.py` (add new test function)

**Interfaces**
- Produces: `MessageInput(content: str, source_ids: list[str] | None = None)`.

**Steps**

1. Write the failing test. Append to `tests/unit/test_schemas.py`:

```python
def test_message_input_source_ids_default_and_parse():
    from apps.api.schemas.chat import MessageInput

    # default omitted -> None (backward compat)
    assert MessageInput(content="q").source_ids is None
    # explicit allowlist parses
    mi = MessageInput(content="q", source_ids=["a", "b"])
    assert mi.source_ids == ["a", "b"]
```

2. Run it to see it fail:

```
uv run pytest tests/unit/test_schemas.py::test_message_input_source_ids_default_and_parse
```

Expected failure: `AttributeError: 'MessageInput' object has no attribute 'source_ids'`.

3. Minimal implementation — edit `apps/api/schemas/chat.py`, replace the `MessageInput` class (L8-9):

```python
class MessageInput(BaseModel):
    content: str = Field(min_length=1)
    source_ids: list[str] | None = None
```

4. Run to pass:

```
uv run pytest tests/unit/test_schemas.py
```

Expected: new test passes, existing schema tests unaffected.

5. Commit:

```
git add apps/api/schemas/chat.py tests/unit/test_schemas.py
git commit -m "feat(api): MessageInput に source_ids を追加 (#6)"
```

---

### Task F.5 — chat router send_message: pass body.source_ids into generation.run

**Files**
- Modify: `apps/api/routers/chat.py`
- Test: `tests/integration/test_api/test_chat_source_ids.py` (Create)

**Interfaces**
- Consumes: `MessageInput.source_ids` (Task F.4), `ctx.generation.run(..., source_ids=...)` (Task F.3).
- Produces: SSE `POST /api/notebooks/{nb}/conversations/{conv}/messages` now forwards `source_ids` to generation.

**Steps**

1. 既存 API テストの fixture 規約を確認する。このリポジトリは `app_ctx` のような `(client, ctx)` タプル fixture を**持たない**。実際の規約(`tests/integration/test_api/test_sources_api.py` / `test_recording_stop_dispatch.py`)は: ローカルに `client` fixture を定義(`NOTEBOOK_OLLAMA_DATA_DIR` を tmp に設定して `TestClient(create_app())`)、context は **`client.app.state.ctx`** で取得し、Ollama 不要なら**構築後に** `ctx.generation.run` を差し替える。開いて確認:

```
uv run python -c "print(open('tests/integration/test_api/test_recording_stop_dispatch.py').read()[:1200])"
```

Expected: `client` fixture + `client.app.state.ctx` 経由で `ctx.<service>` を post-build で差し替えるパターンが見える(`app_ctx` は存在しない)。

2. 失敗するテストを書く。`tests/integration/test_api/test_chat_source_ids.py` を新規作成。`client` fixture(`client.app.state.ctx` で ctx 取得)で `ctx.generation.run` を fake に差し替え、ルータが `source_ids` を透過することを検証する(`NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT=http://fake` で実 Ollama を遮断するが、`generation.run` 差し替えにより実呼び出しは起きない)。`asyncio_mode=auto`(pyproject)なので marker 不要:

```python
import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    with TestClient(create_app()) as c:
        yield c


async def test_send_message_forwards_source_ids(client):
    ctx = client.app.state.ctx
    nb = client.post("/api/notebooks", json={"name": "N"}).json()
    conv = client.post(f"/api/notebooks/{nb['id']}/conversations").json()

    captured = {}

    async def fake_run(**kwargs):
        captured.update(kwargs)
        from core.generation.stream import GenerationEvent

        yield GenerationEvent(kind="retrieval", data={"hits": []})
        yield GenerationEvent(
            kind="done",
            data={"answer": "", "citations": [], "model_used": "m", "dropped_history": 0},
        )

    ctx.generation.run = fake_run

    with client.stream(
        "POST",
        f"/api/notebooks/{nb['id']}/conversations/{conv['id']}/messages",
        json={"content": "質問", "source_ids": ["SRC_A"]},
    ) as resp:
        for _ in resp.iter_lines():
            pass

    assert captured["source_ids"] == ["SRC_A"]
```

> Note: the `num_ctx` resolution path calls `OllamaClient.show`. If the existing `test_api` fixture already fakes Ollama (check Step 1's template), reuse that. If not, also monkeypatch `apps.api.routers.chat.OllamaClient` to a stub whose `show` returns `{"parameters": "num_ctx 8192"}` so the test stays offline — copy whatever stubbing the template test uses.

3. Run it to see it fail:

```
uv run pytest tests/integration/test_api/test_chat_source_ids.py
```

Expected failure: `KeyError: 'source_ids'` (router does not yet pass it through), assuming the fixture/Ollama-stub wiring resolves.

4. Minimal implementation — edit `apps/api/routers/chat.py`. In `send_message`, add the kwarg to the `ctx.generation.run(...)` call (L111-121); insert `source_ids=body.source_ids,` after `notebook_id=notebook_id,`:

```python
        async for ev in ctx.generation.run(
            notebook_id=notebook_id,
            source_ids=body.source_ids,
            model=model,
            question=body.content,
            history=history,
            num_ctx=num_ctx,
            context_budget_ratio=ctx.config.generation.context_budget_ratio,
            response_budget_tokens=ctx.config.generation.response_budget_tokens,
            retrieval_top_k=ctx.config.retrieval.top_k,
            min_history_turns=ctx.config.retrieval.min_history_turns,
        ):
```

5. Run to pass:

```
uv run pytest tests/integration/test_api/test_chat_source_ids.py
```

Expected: 1 passed (`captured["source_ids"] == ["SRC_A"]`).

6. Commit:

```
git add apps/api/routers/chat.py tests/integration/test_api/test_chat_source_ids.py
git commit -m "feat(api): send_message が source_ids を generation.run へ転送 (#6)"
```

---

### Task F.6 — Frontend chat API client: include source_ids in POST body

**Files**
- Modify: `apps/web/src/lib/api/chat.ts`
- Test: none (typecheck + build gate; no unit test for fetch wrapper in this repo's convention)

**Interfaces**
- Produces: `chatApi.sendMessage(notebookId, conversationId, content, sourceIds?: string[], signal?: AbortSignal)` — POST body becomes `{ content, source_ids: sourceIds }`.
- Note: `sourceIds` is inserted **before** the existing optional `signal` param; the store call site (Task F.7) is updated in the same plan so the new arg order is consistent.

**Steps**

1. Update the `sendMessage` signature and body in `apps/web/src/lib/api/chat.ts`. Replace the signature (L33-38) and the `body:` line (L44):

```ts
  sendMessage: async function* (
    notebookId: string,
    conversationId: string,
    content: string,
    sourceIds?: string[],
    signal?: AbortSignal,
  ): AsyncGenerator<ChatEvent, void, unknown> {
    const url = `/api/notebooks/${notebookId}/conversations/${conversationId}/messages`;
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ content, source_ids: sourceIds }),
      signal,
    });
```

2. Typecheck:

```
cd apps/web && npm run check
```

Expected: 0 errors. (The call site in `conversation.svelte.ts` still passes the old arg order — it currently calls `api.sendMessage(notebookId, conv.id, content, abortController.signal)`, so `signal` now lands in the `sourceIds` slot. This is fixed in Task F.7; `npm run check` here may flag the type mismatch — that is expected and resolved in the next task. If `check` reports the mismatch, proceed to F.7 before committing; otherwise commit now.)

3. Commit:

```
git add apps/web/src/lib/api/chat.ts
git commit -m "feat(web): chat API client が source_ids を POST body に含める (#6)"
```

---

### Task F.7 — conversation store send(): accept and forward source_ids

**Files**
- Modify: `apps/web/src/lib/stores/conversation.svelte.ts`
- Test: none (typecheck + build gate; component/store-level send is covered by the visual gate, no vitest store test exists for the SSE send path)

**Interfaces**
- Produces: `ConversationStore.send(notebookId: string, content: string, sourceIds?: string[]): Promise<void>` — forwards `sourceIds` to `api.sendMessage(notebookId, conv.id, content, sourceIds, abortController.signal)`.

**Steps**

1. Update the interface declaration in `apps/web/src/lib/stores/conversation.svelte.ts`. Replace the `send` line in the `ConversationStore` interface (L19):

```ts
  send(notebookId: string, content: string, sourceIds?: string[]): Promise<void>;
```

2. Update the `send` implementation signature (L62):

```ts
    async send(notebookId, content, sourceIds) {
```

3. Update the `api.sendMessage(...)` call (L85-90) to pass `sourceIds` in its new slot before the signal:

```ts
        for await (const ev of api.sendMessage(
          notebookId,
          conv.id,
          content,
          sourceIds,
          abortController.signal,
        ) as AsyncGenerator<ChatEvent>) {
```

4. Typecheck:

```
cd apps/web && npm run check
```

Expected: 0 errors (arg order now consistent end-to-end with Task F.6).

5. Commit:

```
git add apps/web/src/lib/stores/conversation.svelte.ts
git commit -m "feat(web): conversation store send が source_ids を転送 (#6)"
```

---

### Task F.8 — ChatPanel: pass selected source IDs on send (end-to-end wiring)

**Files**
- Modify: `apps/web/src/lib/components/ChatPanel.svelte`
- Test: none here (typecheck + build); Playwright visual-verification gate noted below (run by the controller)

**Interfaces**
- Consumes: `currentNotebookStore.selectedSourceIds: ReadonlySet<string>` (`apps/web/src/lib/stores/currentNotebook.svelte.ts` L8); `conversationStore.send(notebookId, text, sourceIds?)` (Task F.7).
- Produces: on send, passes `Array.from(currentNotebookStore.selectedSourceIds)` so an empty selection yields `[]` ⇒ unfiltered (現状維持), a non-empty selection scopes retrieval.

**Steps**

1. Import the current-notebook store and forward the selected IDs. Edit `apps/web/src/lib/components/ChatPanel.svelte`. Add the import (after L4) and update `onSend` (L12-14):

```svelte
<script lang="ts">
  import MessageList from './MessageList.svelte';
  import ChatInput from './ChatInput.svelte';
  import { conversationStore } from '$lib/stores/conversation.svelte';
  import { currentNotebookStore } from '$lib/stores/currentNotebook.svelte';

  interface Props {
    notebookId: string;
    onCitationClick: (chunkId: string) => void;
  }
  let { notebookId, onCitationClick }: Props = $props();

  function onSend(text: string) {
    conversationStore.send(
      notebookId,
      text,
      Array.from(currentNotebookStore.selectedSourceIds),
    );
  }
</script>
```

> Note: `Array.from(...)` on an empty `Set` gives `[]`; the backend treats empty/None as unfiltered, so leaving all sources unchecked preserves the existing all-sources behavior.

2. Typecheck:

```
cd apps/web && npm run check
```

Expected: 0 errors.

3. Build:

```
cd apps/web && npm run build
```

Expected: build succeeds, output to `apps/web/dist/`.

4. Commit:

```
git add apps/web/src/lib/components/ChatPanel.svelte
git commit -m "feat(web): ChatPanel が選択ソースIDを送信時に渡す (#6)"
```

5. **Playwright visual-verification gate (controller-run, GUI change ⇒ mandatory per CLAUDE.md / MEMORY visual gate):** with API (`uv run uvicorn apps.api.main:app --port 8765`) and web dev server running, in a notebook with ≥2 sources where some content exists in only one source: (a) leave all unchecked, ask a question whose answer lives only in source B → citation appears (all-sources baseline); (b) check only source A → ask the same B-only question → no citation / different answer; (c) check only source B → answer cites source B. Capture a screenshot of each state. Auto-test GREEN alone does NOT satisfy this gate.

---

### Task F.9 — Full regression sweep

**Files**
- Test: entire suite (no code change)

**Steps**

1. Run the full backend suite (default markers, skips Ollama):

```
uv run pytest
```

Expected: all pre-existing tests (202件) plus the new `source_ids` tests pass; 0 regressions.

2. Run the qdrant-marked integration tests explicitly (the new scoping tests live behind `@pytest.mark.qdrant`):

```
uv run pytest -m qdrant
```

Expected: `test_search_filters_by_source_ids` and `test_retrieval_scopes_to_source_ids` pass alongside existing qdrant tests.

3. Frontend final gate:

```
cd apps/web && npm run check && npm run build
```

Expected: 0 type errors, build succeeds.

> No commit (verification-only task). If anything fails, fix under the owning Task before declaring #6 complete.
```

Plan section for Feature #6 is above. Key source files read and matched to current style: `core/storage/vector_store.py` (search L97-111, payload already has `source_id`, `delete_by_source` uses the same `MatchValue` pattern — `MatchAny` is the multi-value sibling), `core/retrieval/search.py` (search L48-58), `core/generation/stream.py` (`_RetrievalLike` L24-25, `run` L50-67), `apps/api/schemas/chat.py` (`MessageInput` L8-9), `apps/api/routers/chat.py` (`ctx.generation.run` L111-121), `apps/web/src/lib/api/chat.ts` (`sendMessage` L33-44), `apps/web/src/lib/stores/conversation.svelte.ts` (interface L19 + impl L62 + call L85-90), `apps/web/src/lib/components/ChatPanel.svelte`, and `apps/web/src/lib/stores/currentNotebook.svelte.ts` (`selectedSourceIds: ReadonlySet<string>` L8).

Two execution-time caveats the engineer must resolve from real fixtures (I flagged them inline rather than inventing details): (1) Task F.5's `test_api` fixture name and the Ollama `.show()` stub — the exact fixture (`app_ctx`/`client`/`ctx`) and any existing Ollama-faking must be copied from a sibling `tests/integration/test_api/*.py` in Step 1, since I did not read those files. (2) `delete_by_source` in the spec text says "mirror delete_by_source," but it already filters by `source_id` only and needs no change for this feature; I did not modify it (no behavioral need — it deletes by a single source_id, unrelated to the read-path allowlist).

---

## #8 チャット待機UX (pending spinner / SSE heartbeat + Stop + bounded read timeout / send-button correctness)

> 確定設計: `docs/specs/2026-06-19-rag-ux-improvements-design.md` §2 表の #8 行 + §3「#8 チャット待機UX」。(a) `streaming` 即時スピナー(参照中→生成中)、(b) SSEハートビート(`ping` イベント)+ `chat_stream` 読み取りタイムアウト有限化(`OllamaSettings` で設定可能、既定120s)+ `lastBeatAt` 無音~60sで非致命警告 + Stopボタン(既存 `cancel()` をUI接続)、(c) 送信ボタンは空入力で通常表示・`streaming` 中のみトーンダウン+Stop切替、`streaming` 中もテキストエリア編集可。
>
> 前提: 別ブランチ `feature/rag-ux-improvements` で作業(master直接編集禁止)。各バックエンドTaskは `uv run pytest`、各フロントTaskは `cd apps/web && npm run check`(0 errors)+ `npm run build`。GUI変更はPlaywright実機スクショ検証ゲートを通す(自動GREENのみでのPASS禁止、ゲートはコントローラが実行)。

---

### Task H.1 — `OllamaSettings` に `chat_read_timeout_seconds` を追加(既定120s)

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\core\config.py`
- Test: `E:\00_Git\10_NotebookOllama\tests\unit\test_config.py`（無ければ新規作成）

**Interfaces**
- Produces: `OllamaSettings.chat_read_timeout_seconds: float = 120.0`（環境変数 `NOTEBOOK_OLLAMA_OLLAMA__CHAT_READ_TIMEOUT_SECONDS` で上書き可能）

**Steps**

1. 失敗するテストを書く。`tests\unit\test_config.py` が存在する場合は末尾に下記テストを追記、無ければ新規作成する。

```python
from core.config import AppConfig, OllamaSettings


def test_ollama_chat_read_timeout_default():
    assert OllamaSettings().chat_read_timeout_seconds == 120.0


def test_ollama_chat_read_timeout_env_override(monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__CHAT_READ_TIMEOUT_SECONDS", "30")
    cfg = AppConfig()
    assert cfg.ollama.chat_read_timeout_seconds == 30.0
```

2. テストを実行し、失敗を確認する。

```
uv run pytest tests/unit/test_config.py -q
```
期待: `AttributeError: 'OllamaSettings' object has no attribute 'chat_read_timeout_seconds'`（2件失敗）。

3. `core\config.py` の `OllamaSettings` にフィールドを追加する。`request_timeout_seconds` 行の直後に1行追加。

```python
class OllamaSettings(BaseModel):
    endpoint: str = "http://localhost:11434"
    default_model: str = "qwen2.5:14b"
    embedding_model: str = "bge-m3"
    request_timeout_seconds: float = 120.0
    # chat_stream の read タイムアウト(秒)。connect は httpx 既定のまま。
    # 詰まった Ollama が無限ハングせず例外→error イベントで表面化させる。
    chat_read_timeout_seconds: float = 120.0
```

4. テストを再実行し、合格を確認する。

```
uv run pytest tests/unit/test_config.py -q
```
期待: 2 passed。

5. コミットする。

```
git add core/config.py tests/unit/test_config.py
git commit -m "feat(config): chat_stream 用の読み取りタイムアウト設定を追加"
```

---

### Task H.2 — `OllamaClient.chat_stream` に有限な read タイムアウトを配線

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\core\ollama\client.py`
- Test: `E:\00_Git\10_NotebookOllama\tests\integration\test_ollama_client.py`

**Interfaces**
- Consumes: 既存 `OllamaClient.__init__(*, endpoint, timeout=120.0)` に `chat_read_timeout: float | None = None` を追加。
- Produces: `chat_stream` は `httpx.Timeout(connect=<既定>, read=chat_read_timeout, write=<既定>, pool=<既定>)` を用いる。`read` 超過時に `httpx.ReadTimeout`(`httpx.HTTPError` サブクラス)→既存 `except httpx.HTTPError` で `AppError(OLLAMA_UNREACHABLE)` に変換される。

**Steps**

1. 失敗するテストを `tests\integration\test_ollama_client.py` 末尾に追記する（read タイムアウト時に `AppError` へ変換されることを検証）。

```python
from core.exceptions import AppError, ErrorCode


@pytest.mark.asyncio
async def test_chat_stream_read_timeout_raises_app_error():
    with respx.mock() as router:
        router.post("http://fake/api/chat").mock(side_effect=httpx.ReadTimeout("read timed out"))
        client = OllamaClient(endpoint="http://fake", chat_read_timeout=1.0)
        with pytest.raises(AppError) as ei:
            async for _ in client.chat_stream(
                model="qwen2.5:14b",
                messages=[{"role": "user", "content": "hi"}],
            ):
                pass
        assert ei.value.code == ErrorCode.OLLAMA_UNREACHABLE
```

2. テストを実行し、失敗を確認する。

```
uv run pytest tests/integration/test_ollama_client.py::test_chat_stream_read_timeout_raises_app_error -q
```
期待: `TypeError: __init__() got an unexpected keyword argument 'chat_read_timeout'`。

3. `core\ollama\client.py` の `__init__` を変更し、`chat_read_timeout` を保持する。

```python
class OllamaClient:
    def __init__(
        self,
        *,
        endpoint: str,
        timeout: float = 120.0,
        chat_read_timeout: float | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._timeout = timeout
        self._chat_read_timeout = chat_read_timeout
```

4. `chat_stream` の `AsyncClient(timeout=None)` を、connect は既定維持・read のみ有限化した `httpx.Timeout` に差し替える。

```python
        payload = {"model": model, "messages": messages, "stream": True}
        if options:
            payload["options"] = options
        # connect/write/pool は httpx 既定(5s)を維持し、read のみ有限化する。
        # ストリーミング中の各トークン受信間隔に read タイムアウトが適用される。
        timeout = httpx.Timeout(5.0, read=self._chat_read_timeout)
        async with httpx.AsyncClient(timeout=timeout) as client:
```

5. テストを再実行し、合格を確認する。

```
uv run pytest tests/integration/test_ollama_client.py -q
```
期待: 既存4件 + 新規1件 = 5 passed。

6. コミットする。

```
git add core/ollama/client.py tests/integration/test_ollama_client.py
git commit -m "feat(ollama): chat_stream に read タイムアウトを付与し無限ハングを防ぐ"
```

---

### Task H.3 — `build_context` で `chat_read_timeout` を `OllamaClient` に配線

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\apps\api\dependencies.py`
- Test: `E:\00_Git\10_NotebookOllama\tests\integration\test_dependencies.py`（無ければ新規作成）

**Interfaces**
- Consumes: `config.ollama.chat_read_timeout_seconds`（Task H.1）。
- Produces: `build_context` が生成する `OllamaClient` に `chat_read_timeout=config.ollama.chat_read_timeout_seconds` を渡す。

**Steps**

1. 失敗するテストを書く。`tests\integration\test_dependencies.py` に追記/新規作成する。

```python
from core.config import AppConfig
from apps.api.dependencies import build_context


def test_build_context_wires_chat_read_timeout(tmp_path):
    cfg = AppConfig(data_dir=tmp_path)
    cfg.ollama.chat_read_timeout_seconds = 45.0
    ctx = build_context(cfg)
    # OllamaGateway は raw client を保持する
    assert ctx.ollama._client._chat_read_timeout == 45.0
```

2. テストを実行し、失敗を確認する。

```
uv run pytest tests/integration/test_dependencies.py::test_build_context_wires_chat_read_timeout -q
```
期待: `assert None == 45.0`（`_chat_read_timeout` が既定 `None` のまま）で失敗。

3. `apps\api\dependencies.py` の `OllamaClient(...)` 構築に引数を追加する。

```python
    raw_client = OllamaClient(
        endpoint=config.ollama.endpoint,
        timeout=config.ollama.request_timeout_seconds,
        chat_read_timeout=config.ollama.chat_read_timeout_seconds,
    )
```

4. テストを再実行し、合格を確認する。

```
uv run pytest tests/integration/test_dependencies.py -q
```
期待: passed。

5. コミットする。

```
git add apps/api/dependencies.py tests/integration/test_dependencies.py
git commit -m "feat(api): build_context で chat read タイムアウトを OllamaClient に配線"
```

---

### Task H.4 — `send_message` の `EventSourceResponse` に名前付き `ping` ハートビートを付与

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\apps\api\routers\chat.py`
- Test: `E:\00_Git\10_NotebookOllama\tests\integration\test_api\test_chat_api.py`

**Interfaces**
- Consumes: `sse_starlette.sse.EventSourceResponse(content, *, ping: int, ping_message_factory: Callable[[], ServerSentEvent])`、`sse_starlette.event.ServerSentEvent(data, event)`。
- Produces: SSE ストリームが `ping=20`(秒)間隔で `event: ping` / `data: {}` を emit する。既存クライアントは未知イベント無視なので後方互換。

**Steps**

1. 失敗するテストを `tests\integration\test_api\test_chat_api.py` 末尾に追記する（`ping_message_factory` が `event: ping` を生成することを単体検証 — `TestClient` は短時間で ping 間隔に達しないため、ファクトリ関数の出力を直接検証する）。

```python
def test_ping_factory_emits_named_ping_event():
    from apps.api.routers.chat import _ping_event

    sse = _ping_event()
    rendered = b"".join(sse.encode())
    assert b"event: ping" in rendered
    assert b"data: {}" in rendered
```

2. テストを実行し、失敗を確認する。

```
uv run pytest tests/integration/test_api/test_chat_api.py::test_ping_factory_emits_named_ping_event -q
```
期待: `ImportError: cannot import name '_ping_event' from 'apps.api.routers.chat'`。

3. `apps\api\routers\chat.py` の import に `ServerSentEvent` を追加する。

```python
from sse_starlette.sse import EventSourceResponse
from sse_starlette.event import ServerSentEvent
```

4. `send_message` の `return EventSourceResponse(event_gen())` の直前（モジュールレベルでも可）に ping ファクトリを定義する。`event_gen` 関数定義の直前にモジュールレベル関数として追加する。

```python
def _ping_event() -> ServerSentEvent:
    """名前付き ping イベント。フロントが lastBeatAt 更新に使う(未知イベントは無視されるため後方互換)。"""
    return ServerSentEvent(data="{}", event="ping")
```

5. `return EventSourceResponse(event_gen())` を ping 有効化に差し替える。

```python
    return EventSourceResponse(
        event_gen(),
        ping=20,
        ping_message_factory=_ping_event,
    )
```

6. テストを再実行し、合格を確認する。あわせて既存 SSE テストが壊れていないことも確認する。

```
uv run pytest tests/integration/test_api/test_chat_api.py -q
```
期待: 既存 `test_chat_streaming_returns_sse` + 新規 = 全 passed。

7. コミットする。

```
git add apps/api/routers/chat.py tests/integration/test_api/test_chat_api.py
git commit -m "feat(chat): SSE に名前付き ping ハートビート(20s)を追加"
```

---

### Task H.5 — フロント `chat.ts` の `ping` イベントを型に追加して受理

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\api\chat.ts`
- Test: `E:\00_Git\10_NotebookOllama\apps\web\tests\unit\stores\conversation.test.ts`（Task H.7 で本体検証。本Taskは `npm run check` を検証手段とする）

**Interfaces**
- Produces: `ChatEvent` ユニオンに `| { kind: 'ping' }` を追加。`sendMessage` の SSE パーサは既に `kind: currentEvent` を透過するため、`event: ping` / `data: {}` は `{ kind: 'ping' }` として yield される（追加ロジック不要、型のみ拡張）。

**Steps**

1. `apps\web\src\lib\api\chat.ts` の `ChatEvent` ユニオンに `ping` を追加する。

```typescript
export type ChatEvent =
  | { kind: 'retrieval'; hits: RetrievalHit[] }
  | { kind: 'token'; text: string }
  | {
      kind: 'done';
      answer: string;
      citations: Citation[];
      model_used: string;
      dropped_history: number;
    }
  | { kind: 'error'; code: string; message: string }
  | { kind: 'ping' };
```

2. 型チェックを実行する。

```
cd apps/web && npm run check
```
期待: 0 errors（`yield { kind: currentEvent, ...parsed }` の `currentEvent: string` が拡張ユニオンに代入される箇所は既存 `as ChatEvent` キャストでカバー済み。新規エラーが出ないこと）。

3. コミットする。

```
git add apps/web/src/lib/api/chat.ts
git commit -m "feat(web): ChatEvent に ping イベントを追加"
```

---

### Task H.6 — conversation ストアに `lastBeatAt` 追跡 + 無音~60s 非致命警告 + ping ハンドリング

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\stores\conversation.svelte.ts`
- Test: `E:\00_Git\10_NotebookOllama\apps\web\tests\unit\stores\conversation.test.ts`（Task H.7 で記述）

**Interfaces**
- Produces: `ConversationStore` に `readonly warning: string | null`、`readonly lastBeatAt: number | null` を追加。`send` 中、`ping`/`retrieval`/`token` 受信ごとに `lastBeatAt = Date.now()`。`streaming` 中に `setInterval` で監視し、無音 `>= 60s` で `warning = 'Ollamaが応答していない可能性があります'`。ビート再開で `warning = null`。`done`/`error`/`finally`/`cancel` でインターバル停止。

**Steps**

> ⚠️ 依存注意: このタスクは実行順で **#6 Task F.7 の後**に来る。F.7 は既に `conversation.svelte.ts` の `send` を `send(notebookId, content, sourceIds?)` に変更し、`for await` の呼び出しを `api.sendMessage(notebookId, conv.id, content, sourceIds, abortController.signal)`(5引数)にしている。本タスクは**その上に**ビート/ping を**足す**だけで、`send` の `sourceIds` 引数や 5引数呼び出しを**戻してはならない**(戻すと #6 のスコープ配線が壊れ `npm run check` も AbortSignal→string[] で失敗する)。下記コードは F.7 適用後の現物を前提に書いてある。

1. インターフェースに `warning` / `lastBeatAt` を追加する（`conversation.svelte.ts` の `ConversationStore` インターフェース）。`send` の `sourceIds?` 引数(F.7 で追加済み)は保持する。

```typescript
export interface ConversationStore {
  readonly conversation: Conversation | null;
  readonly messages: Message[];
  readonly streaming: boolean;
  readonly streamingText: string;
  readonly streamingHits: RetrievalHit[];
  readonly error: string | null;
  readonly warning: string | null;
  readonly lastBeatAt: number | null;
  load(notebookId: string, conversationId: string): Promise<void>;
  ensureConversation(notebookId: string): Promise<Conversation>;
  send(notebookId: string, content: string, sourceIds?: string[]): Promise<void>;
  cancel(): void;
}
```

2. ストア内部状態に `warning` / `lastBeatAt` / 監視ハンドル / 無音しきい値を追加する（`let error = $state<string | null>(null);` の直後）。

```typescript
  let error = $state<string | null>(null);
  let warning = $state<string | null>(null);
  let lastBeatAt = $state<number | null>(null);
  let abortController: AbortController | null = null;
  let beatTimer: ReturnType<typeof setInterval> | null = null;
  const NO_BEAT_WARNING_MS = 60_000;

  function beat() {
    lastBeatAt = Date.now();
    if (warning) warning = null;
  }

  function startBeatWatch() {
    stopBeatWatch();
    beat();
    beatTimer = setInterval(() => {
      if (lastBeatAt !== null && Date.now() - lastBeatAt >= NO_BEAT_WARNING_MS) {
        warning = 'Ollamaが応答していない可能性があります';
      }
    }, 5_000);
  }

  function stopBeatWatch() {
    if (beatTimer !== null) {
      clearInterval(beatTimer);
      beatTimer = null;
    }
  }
```

3. ゲッターに `warning` / `lastBeatAt` を追加する（`get error()` の直後）。

```typescript
    get error() {
      return error;
    },
    get warning() {
      return warning;
    },
    get lastBeatAt() {
      return lastBeatAt;
    },
```

4. `send` の状態初期化と監視開始を配線する。`streaming = true;` ブロックを下記に差し替える。

```typescript
      messages = [...messages, userMsg];
      streaming = true;
      streamingText = "";
      streamingHits = [];
      error = null;
      warning = null;
      abortController = new AbortController();
      startBeatWatch();
```

5. SSE ループの各イベントでビートを刻み、`ping` を処理する。`for await` 内の `if/else` チェーンを差し替える。**`api.sendMessage` の呼び出しは F.7 の 5引数形(`sourceIds` を `signal` の前に渡す)を維持する** — 引数を落とさないこと。

```typescript
        for await (const ev of api.sendMessage(
          notebookId,
          conv.id,
          content,
          sourceIds,
          abortController.signal,
        ) as AsyncGenerator<ChatEvent>) {
          beat();
          if (ev.kind === "ping") {
            // beat() 済み。接続生存のみ確認
          } else if (ev.kind === "retrieval") {
            streamingHits = ev.hits;
          } else if (ev.kind === "token") {
            streamingText += ev.text;
          } else if (ev.kind === "done") {
            citations = ev.citations;
            modelUsed = ev.model_used;
            streamingText = ev.answer;
          } else if (ev.kind === "error") {
            error = ev.message;
          }
        }
```

6. `finally` で監視停止と状態リセットを行う。`finally` ブロックを差し替える。

```typescript
      } finally {
        streaming = false;
        streamingText = "";
        streamingHits = [];
        abortController = null;
        stopBeatWatch();
        lastBeatAt = null;
        warning = null;
      }
```

7. `cancel()` で監視を停止する。

```typescript
    cancel() {
      abortController?.abort();
      stopBeatWatch();
    },
```

8. 型チェックを実行する。

```
cd apps/web && npm run check
```
期待: 0 errors。

9. コミットする。

```
git add apps/web/src/lib/stores/conversation.svelte.ts
git commit -m "feat(web): conversation ストアに lastBeatAt/無音警告と ping 処理を追加"
```

---

### Task H.7 — conversation ストアの vitest ユニットテスト（lastBeatAt / ping / warning / cancel）

**Files**
- Test: `E:\00_Git\10_NotebookOllama\apps\web\tests\unit\stores\conversation.test.ts`（新規）

**Interfaces**
- Consumes: `createConversationStore(api)`（`api` は `chatApi` 互換の最小モック）。`api.sendMessage` は `AsyncGenerator<ChatEvent>` を返すモックにする。`vi.useFakeTimers()` で無音60s経過をシミュレートする。

**Steps**

1. テストを新規作成する。`createConversationStore` のエクスポートは `conversation.svelte.ts` に既存（末尾 `export const conversationStore = ...` の上で `export function createConversationStore` 済み）。`.svelte.ts` のため runes をテスト実行できるよう、vitest の svelte プラグインで処理される（既存 `recording.svelte` テストと同様に `$lib/stores/...` を import するだけで動作する）。

```typescript
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { createConversationStore } from '$lib/stores/conversation.svelte';
import type { ChatEvent } from '$lib/api/chat';
import type { Conversation } from '$lib/api/types';

// notify は Notification API を触るため無効化する
vi.mock('$lib/utils/notifications', () => ({
  notify: vi.fn(),
  requestPermissionOnce: vi.fn(),
}));

const conv: Conversation = {
  id: 'c1',
  notebook_id: 'nb1',
  title: null,
  created_at: '2026-06-19T00:00:00Z',
  updated_at: '2026-06-19T00:00:00Z',
};

function makeApi(events: ChatEvent[], opts: { hold?: boolean } = {}) {
  return {
    createConversation: vi.fn().mockResolvedValue(conv),
    listMessages: vi.fn().mockResolvedValue([]),
    sendMessage: vi.fn(function* () {
      for (const ev of events) yield ev;
      // hold=true のときはここで返らず、呼び側が手動で進める想定では使わない
    }),
  };
}

describe('conversation store', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('ping/token 受信で lastBeatAt が更新され warning は立たない', async () => {
    const events: ChatEvent[] = [
      { kind: 'ping' },
      { kind: 'token', text: 'こん' },
      { kind: 'token', text: 'にちは' },
      {
        kind: 'done',
        answer: 'こんにちは',
        citations: [],
        model_used: 'qwen2.5:14b',
        dropped_history: 0,
      },
    ];
    const store = createConversationStore(makeApi(events) as never);
    await store.send('nb1', '質問');
    // done 後は finally でリセットされ streaming=false, warning=null
    expect(store.streaming).toBe(false);
    expect(store.warning).toBeNull();
    expect(store.messages.at(-1)?.content).toBe('こんにちは');
  });

  it('60s ビート途絶で warning が立つ(ストリーム保留中)', async () => {
    // sendMessage を「token 1回 → 以降保留」にして streaming 中に時間を進める
    let resolveGen!: () => void;
    const gate = new Promise<void>((r) => (resolveGen = r));
    const api = {
      createConversation: vi.fn().mockResolvedValue(conv),
      listMessages: vi.fn().mockResolvedValue([]),
      sendMessage: vi.fn(async function* () {
        yield { kind: 'token', text: 'A' } as ChatEvent;
        await gate; // ここで保留 = ストリーム継続中
      }),
    };
    const store = createConversationStore(api as never);
    const p = store.send('nb1', '質問');
    // streaming 中: 監視タイマーを 65s 進める
    await vi.advanceTimersByTimeAsync(65_000);
    expect(store.streaming).toBe(true);
    expect(store.warning).toBe('Ollamaが応答していない可能性があります');
    // ストリームを閉じて後始末
    resolveGen();
    await vi.advanceTimersByTimeAsync(0);
    await p;
    expect(store.warning).toBeNull();
  });

  it('cancel() で abort され streaming/監視が止まる', async () => {
    let resolveGen!: () => void;
    const gate = new Promise<void>((r) => (resolveGen = r));
    const api = {
      createConversation: vi.fn().mockResolvedValue(conv),
      listMessages: vi.fn().mockResolvedValue([]),
      sendMessage: vi.fn(async function* (
        _nb: string,
        _cid: string,
        _content: string,
        signal?: AbortSignal,
      ) {
        yield { kind: 'token', text: 'A' } as ChatEvent;
        await gate;
        if (signal?.aborted) return;
      }),
    };
    const store = createConversationStore(api as never);
    const p = store.send('nb1', '質問');
    await vi.advanceTimersByTimeAsync(0);
    expect(store.streaming).toBe(true);
    store.cancel();
    resolveGen();
    await p;
    expect(store.streaming).toBe(false);
    expect(store.warning).toBeNull();
  });
});
```

2. テストを実行し、合格を確認する。

```
cd apps/web && npm run test:unit -- conversation
```
期待: 3 tests passed（`conversation.test.ts`）。

3. コミットする。

```
git add apps/web/tests/unit/stores/conversation.test.ts
git commit -m "test(web): conversation ストアの lastBeatAt/ping/warning/cancel を検証"
```

---

### Task H.8 — `MessageList` を `streaming` 即時表示にし「参照中…→生成中…」スピナーを出す

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\MessageList.svelte`
- Test: なし（純UI。検証は `npm run check` + `npm run build` + Playwright視覚検証ゲート）

**Interfaces**
- Consumes: `conversationStore.streaming`, `.streamingText`, `.streamingHits`, `.warning`, 既存 `Spinner`。
- Produces: `streaming===true && !streamingText` の間、ヒット未到着なら「参照中…」、ヒット到着後〜初トークンまで「生成中…」をインラインスピナー付きで表示。トークン到着後は既存の部分Markdown+caret へ遷移。`warning` を非致命バナーとして表示。

**Steps**

1. `MessageList.svelte` の `{#if conversationStore.streaming && conversationStore.streamingText}` ブロックを、pending 分岐を含む形に差し替える。

```svelte
  {#if conversationStore.streaming}
    <article class="msg streaming">
      <div class="role">アシスタント</div>
      {#if conversationStore.streamingText}
        {#if conversationStore.streamingHits.length > 0}
          <div class="hits">参照中: {conversationStore.streamingHits.length} ソース</div>
        {/if}
        <div class="content">{@html injectCitationBadges(renderMarkdown(conversationStore.streamingText), [])}</div>
        <div class="caret"><Spinner size={10} /> 生成中…</div>
      {:else}
        <div class="pending">
          <Spinner size={12} />
          {conversationStore.streamingHits.length > 0 ? '生成中…' : '参照中…'}
        </div>
      {/if}
    </article>
  {/if}

  {#if conversationStore.warning}
    <div class="warn">{conversationStore.warning}</div>
  {/if}
```

2. `pending` と `warn` のスタイルを `<style>` の `.caret { ... }` ルールの直後に追加する。

```css
  .pending {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    font-size: 12px;
    color: var(--color-fg-muted);
  }
  .warn {
    padding: var(--space-2) var(--space-4);
    font-size: 12px;
    color: var(--color-warning, #b45309);
  }
```

3. 型チェックとビルドを実行する。

```
cd apps/web && npm run check && npm run build
```
期待: 0 errors / build 成功。

4. コミットする。

```
git add apps/web/src/lib/components/MessageList.svelte
git commit -m "feat(web): 送信直後に参照中→生成中スピナーを即時表示し無音警告を表示"
```

> Playwright視覚検証ゲート（コントローラ実行）: 質問送信直後にトークン到着前から「参照中…」→（ヒット到着後）「生成中…」スピナーが出ること、トークン到着で部分Markdown+caretに遷移することをスクショ確認。

---

### Task H.9 — `ChatInput` の送信ボタン是正（空入力で通常表示・`streaming` 中のみトーンダウン/Stop切替・テキストエリア常時編集可）

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\ChatInput.svelte`
- Test: なし（純UI。検証は `npm run check` + `npm run build` + Playwright視覚検証ゲート）

**Interfaces**
- Consumes: `streaming: boolean`, `onSend: (text: string) => void`, `onCancel: () => void`（新規 prop）。`disabled` prop は廃止し `streaming` に統一。
- Produces: `streaming===false` のとき通常色の送信ボタン（空入力でもトーンダウンしない、`submit()` が空をno-op）。`streaming===true` のとき送信ボタンを danger 系 Stop ボタンに切替（`onCancel()` 呼び出し）。テキストエリアは常に編集可。

**Steps**

1. `ChatInput.svelte` の `<script>` の Props と import を差し替える（`Send` に加え `Square` を追加、`disabled` を `streaming`/`onCancel` に置換）。

```svelte
<script lang="ts">
  import Button from './Button.svelte';
  import { Send, Square } from '@lucide/svelte';

  interface Props {
    streaming: boolean;
    hint?: string | null;
    onSend: (text: string) => void;
    onCancel: () => void;
  }
  let { streaming, hint = null, onSend, onCancel }: Props = $props();

  let value = $state('');

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      submit();
    }
  }

  function submit() {
    if (streaming) return;
    const t = value.trim();
    if (!t) return;
    onSend(t);
    value = '';
  }
</script>
```

2. テンプレート（`<form>`）を差し替える。テキストエリアの `{disabled}` を撤去（常時編集可）、ボタンを `streaming` で送信/Stop切替にする。

```svelte
<form class="input" onsubmit={(e) => { e.preventDefault(); submit(); }}>
  <textarea
    bind:value
    placeholder="質問を入力（Cmd/Ctrl+Enter で送信）"
    rows="3"
    onkeydown={onKey}
  ></textarea>
  <div class="row">
    <span class="hint">{hint ?? ''}</span>
    {#if streaming}
      <Button type="button" variant="danger" onclick={onCancel}>
        <Square size={14} /> 停止
      </Button>
    {:else}
      <Button type="submit">
        <Send size={14} /> 送信
      </Button>
    {/if}
  </div>
</form>
```

3. 型チェックとビルドを実行する。

```
cd apps/web && npm run check && npm run build
```
期待: 0 errors（`ChatPanel` 側の prop 不整合は Task H.10 で解消。本Task単独では `npm run check` が `ChatPanel.svelte` で `disabled`/`onCancel` 不一致エラーを出すため、H.9 と H.10 は連続して実装し、`check` は H.10 後に通す）。

> 注: H.9 単独コミット時点では `npm run check` が `ChatPanel.svelte` 由来でエラーになる。本リポジトリ慣習に従い、H.9 と H.10 を1サイクルとして扱い、`check`/`build` のグリーン確認は H.10 のステップで行う。

4. コミットする（check は次Taskで確定）。

```
git add apps/web/src/lib/components/ChatInput.svelte
git commit -m "feat(web): ChatInput を空入力で通常表示・streaming 中のみ Stop 切替に是正"
```

---

### Task H.10 — `ChatPanel` で `streaming`/`cancel` を `ChatInput` に配線（Stop配線完了）

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\ChatPanel.svelte`
- Test: なし（純UI。検証は `npm run check` + `npm run build` + Playwright視覚検証ゲート）

**Interfaces**
- Consumes: `conversationStore.streaming`, `conversationStore.cancel()`。
- Produces: `ChatInput` へ `streaming={conversationStore.streaming}` と `onCancel={() => conversationStore.cancel()}` を渡す。`disabled` prop は廃止。

**Steps**

1. `ChatPanel.svelte` の `<ChatInput .../>` を差し替える。

```svelte
<MessageList {onCitationClick} />
<ChatInput
  streaming={conversationStore.streaming}
  hint={conversationStore.messages.length > 0
    ? `履歴: 直近${Math.min(3, Math.floor(conversationStore.messages.length / 2))}往復が含まれます`
    : null}
  {onSend}
  onCancel={() => conversationStore.cancel()}
/>
```

2. 型チェックとビルドを実行する（H.9 + H.10 の合算で確定）。

```
cd apps/web && npm run check && npm run build
```
期待: 0 errors / build 成功。

3. ストアのユニットテストを含むフロント全体のユニットテストが緑であることを確認する。

```
cd apps/web && npm run test:unit
```
期待: 既存 + `conversation.test.ts` 全 passed。

4. コミットする。

```
git add apps/web/src/lib/components/ChatPanel.svelte
git commit -m "feat(web): ChatPanel から streaming/cancel を ChatInput に配線し Stop を有効化"
```

> Playwright視覚検証ゲート（コントローラ実行、本フィーチャ統合確認）:
> 1. 送信直後にスピナー（参照中→生成中）が初トークン前に表示される。
> 2. 空入力時に送信ボタンが通常色のまま（トーンダウンしない）、押下しても無反応。
> 3. 返答待ち中に「停止」ボタンが現れ、押すとストリームが中断され `streaming` が解除される。
> 4. 返答待ち中もテキストエリアが編集可能。
> 5. Ollama停止（または read タイムアウト）状態で約60秒後に「Ollamaが応答していない可能性があります」警告が表示される。

---

## #5 録音再生成(再埋め込み)

> 設計確定: `docs/specs/2026-06-19-rag-ux-improvements-design.md` §2 #5 行 + §3「#5 録音再生成(再埋め込み)」。状態は `ready` 維持(0チャンクでもerror化しない)。再生成ボタンは `recording && (status==='error' || (chunk_count===0 && status==='ready')) && has_audio` のとき表示。圧縮音源(.m4a/.opus/.mp3)から再STT(faster-whisper が PyAV でデコード)。WAV削除済みのため圧縮音源が唯一の再STT手段。本仕様の決定は固定であり再設計しない。
>
> 前提ブランチ: `feature/rag-ux-improvements`(master直接編集禁止)。各 Task は独立した test cycle を持ち、それぞれが新規レビュアーのゲートになる粒度で分割している。バックエンドは実 pytest、フロント(Svelte 5 runes)はコンポーネント単体テスト規約が無いため `npm run check`(0 errors)+ `npm run build` + Playwright 実機スクショ検証ゲート(コントローラが実行)を「テスト」とする。

### Task E.1 `Source` スキーマに `has_audio` を追加し、ソース一覧/単体 API で返す(バックエンド)

録音ソースの `sources_dir/<id>/` にチャンネル音源(mic/system の .m4a/.opus/.mp3/.wav)が存在するかを `has_audio: bool` として計算し、`Source` スキーマと全シリアライズ経路(GET 一覧・retry・upload の戻り)に反映する。`_resolve_audio_path` / `_AUDIO_EXT_PRIORITY` を `audio.py` から再利用する。

**Files**
- Modify: `apps/api/schemas/source.py`(`Source` に `has_audio: bool` フィールド追加)
- Modify: `apps/api/routers/sources.py`(`_to_schema` を `sources_dir` 受け取りに変更し `has_audio` を計算、全呼び出し箇所を更新)
- Test: `tests/integration/test_api/test_source_has_audio.py`(新規)

**Interfaces**
- Consumes: `apps.api.routers.audio._resolve_audio_path(base: Path, channel: str) -> Path | None`、`_AUDIO_EXT_PRIORITY: tuple[str, ...]`
- Consumes: `sources_repo.SourceRecord`、`ctx.config.sources_dir: Path`
- Produces: `Source(..., has_audio: bool)`(`has_audio` は録音以外では常に `False`、録音は `sources_dir/<id>/{mic,system}` のいずれかに音源があれば `True`)
- Produces: `_to_schema(rec: SourceRecord, sources_dir: Path) -> Source`

**Steps**

1. (失敗するテストを書く)`tests/integration/test_api/test_source_has_audio.py` を新規作成:
   ```python
   """GET /sources が録音ソースの has_audio を音源ファイルの有無から計算することを検証する。"""

   import pytest
   from fastapi.testclient import TestClient

   from apps.api.main import create_app


   @pytest.fixture
   def client(tmp_path, monkeypatch):
       monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
       app = create_app()
       with TestClient(app) as c:
           yield c


   def _create_nb(client) -> str:
       return client.post("/api/notebooks", json={"name": "has_audio"}).json()["id"]


   def test_recording_with_audio_reports_has_audio_true(client):
       nb = _create_nb(client)
       ctx = client.app.state.ctx
       from core.storage import sources_repo

       src = sources_repo.create_source(
           ctx.conn, notebook_id=nb, kind="recording", title="rec", origin="録音"
       )
       d = ctx.config.sources_dir / src.id
       d.mkdir(parents=True, exist_ok=True)
       (d / "mic.m4a").write_bytes(b"\x00" * 128)

       rows = client.get(f"/api/notebooks/{nb}/sources").json()
       got = next(r for r in rows if r["id"] == src.id)
       assert got["has_audio"] is True


   def test_recording_without_audio_reports_has_audio_false(client):
       nb = _create_nb(client)
       ctx = client.app.state.ctx
       from core.storage import sources_repo

       src = sources_repo.create_source(
           ctx.conn, notebook_id=nb, kind="recording", title="rec", origin="録音"
       )
       (ctx.config.sources_dir / src.id).mkdir(parents=True, exist_ok=True)

       rows = client.get(f"/api/notebooks/{nb}/sources").json()
       got = next(r for r in rows if r["id"] == src.id)
       assert got["has_audio"] is False
   ```

2. (失敗を確認)実行: `uv run pytest tests/integration/test_api/test_source_has_audio.py -q`
   期待する失敗: `KeyError: 'has_audio'`(レスポンスに `has_audio` キーが無い)。

3. (最小実装: スキーマ)`apps/api/schemas/source.py` の `Source` に `chunk_count` の次行へ追加:
   ```python
       chunk_count: int | None
       has_audio: bool = False
   ```

4. (最小実装: シリアライザ)`apps/api/routers/sources.py` の import に `Path`(標準)を足さず、既存 `from fastapi import ... Path` と衝突しないよう `pathlib` は使わず `ctx.config.sources_dir` の `Path` をそのまま使う。`audio.py` のヘルパを import し、`_to_schema` を差し替える。先頭の import 群へ追加:
   ```python
   from apps.api.routers.audio import _AUDIO_EXT_PRIORITY, _resolve_audio_path
   ```
   `_to_schema` を以下へ置換:
   ```python
   def _has_recording_audio(rec, sources_dir) -> bool:
       if rec.kind != "recording":
           return False
       base = sources_dir / rec.id
       if not base.is_dir():
           return False
       return any(
           _resolve_audio_path(base, ch) is not None for ch in ("mic", "system")
       )


   def _to_schema(rec, sources_dir) -> Source:
       return Source(
           id=rec.id,
           notebook_id=rec.notebook_id,
           kind=rec.kind,
           title=rec.title,
           origin=rec.origin,
           status=rec.status.value,
           error_msg=rec.error_msg,
           bytes=rec.bytes,
           page_count=rec.page_count,
           chunk_count=rec.chunk_count,
           has_audio=_has_recording_audio(rec, sources_dir),
           created_at=rec.created_at,
           updated_at=rec.updated_at,
       )
   ```
   注: `_AUDIO_EXT_PRIORITY` は `_resolve_audio_path` 内部で使うため import 済みにしておく(将来直接参照する箇所で未定義にしない)。

5. (最小実装: 呼び出し更新)`apps/api/routers/sources.py` の `_to_schema` 呼び出し4箇所に `ctx.config.sources_dir` を渡す:
   - L92 `return _to_schema(rec)` → `return _to_schema(rec, ctx.config.sources_dir)`
   - L159 `return _to_schema(rec)` → `return _to_schema(rec, ctx.config.sources_dir)`
   - L166 `return [_to_schema(r) for r in sources_repo.list_sources(...)]` → `return [_to_schema(r, ctx.config.sources_dir) for r in sources_repo.list_sources(ctx.conn, notebook_id=notebook_id)]`
   - L244 `return _to_schema(sources_repo.get_source(ctx.conn, source_id))` → `return _to_schema(sources_repo.get_source(ctx.conn, source_id), ctx.config.sources_dir)`

6. (パスを確認)実行: `uv run pytest tests/integration/test_api/test_source_has_audio.py -q`
   期待: 2 passed。

7. (回帰確認)実行: `uv run pytest tests/integration/test_api -q`
   期待: 既存ソース系テストを含め全 pass(`_to_schema` シグネチャ変更の波及が無いこと)。

8. (コミット)
   ```
   git add apps/api/schemas/source.py apps/api/routers/sources.py tests/integration/test_api/test_source_has_audio.py
   git commit -m "feat(api): Source に has_audio を追加し録音音源の有無を一覧/単体で返す"
   ```

### Task E.2 録音再生成エンドポイント `POST /recordings/{sid}/retry`(バックエンド)

`stop_recording` の dispatch を共有ヘルパ `_dispatch_recording_pipeline` に抽出し、新エンドポイントから再利用する。チャンネル別に圧縮音源 or wav を解決、両チャンネル音源無しなら 422、チャンクをクリアして `status=PARSING`、`recording_pipeline.run` を background dispatch する。

**Files**
- Modify: `apps/api/routers/recordings.py`(`_dispatch_recording_pipeline` 抽出 + `retry_recording` 追加)
- Test: `tests/integration/test_api/test_recording_retry_dispatch.py`(新規)

**Interfaces**
- Consumes: `audio._resolve_audio_path`, `audio._AUDIO_EXT_PRIORITY`、`_get_transcriber(request)`, `_get_diarizer(request)`, `_resolve_wav(p)`
- Consumes: `sources_repo.get_source`, `update_source_status(status=SourceStatus.PARSING)`、`core.storage.chunks_repo.delete_chunks_for_source(conn, source_id)`、`ctx.vector_store.delete_by_source(source_id)`、`ctx.recording_pipeline.run(...)`
- Produces: `POST /api/notebooks/{notebook_id}/recordings/{sid}/retry` → `{"source_id": str, "status": "processing"}`、音源欠如時 `HTTPException(422)`
- Produces: `_dispatch_recording_pipeline(request, background, *, notebook_id, source_id, mic_audio, system_audio) -> None`(stop と retry 共通の dispatch)

**Steps**

1. (失敗するテストを書く)`tests/integration/test_api/test_recording_retry_dispatch.py` を新規作成(`test_recording_stop_dispatch.py` の fake パターンを踏襲):
   ```python
   """POST /recordings/{sid}/retry が圧縮音源から再STTパイプラインを再ディスパッチし、
   既存チャンク(sqlite + ベクタ)をクリアすることを検証する統合テスト。

   実 whisper / sherpa はロードしない。recording_pipeline を kwargs 記録 fake に差し替える。
   """

   from pathlib import Path

   import pytest
   from fastapi.testclient import TestClient

   from apps.api.main import create_app
   from core.storage import sources_repo
   from core.storage.chunks_repo import delete_chunks_for_source  # noqa: F401  (import 健全性)


   class _FakePipeline:
       def __init__(self):
           self.calls: list[dict] = []

       async def run(self, **kwargs):
           self.calls.append(kwargs)


   class _FakeVectorStore:
       def __init__(self):
           self.deleted: list[str] = []

       def delete_by_source(self, source_id):
           self.deleted.append(source_id)


   @pytest.fixture
   def client(tmp_path, monkeypatch):
       monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
       app = create_app()
       with TestClient(app) as c:
           ctx = c.app.state.ctx
           ctx.transcriber_factory = lambda: object()
           ctx.diarizer_factory = lambda: None
           yield c


   def _create_nb(client) -> str:
       return client.post("/api/notebooks", json={"name": "retry"}).json()["id"]


   def _seed_recording(client, nb, *, with_audio: bool, channel="mic", ext=".m4a"):
       ctx = client.app.state.ctx
       src = sources_repo.create_source(
           ctx.conn, notebook_id=nb, kind="recording", title="rec", origin="録音"
       )
       d = ctx.config.sources_dir / src.id
       d.mkdir(parents=True, exist_ok=True)
       if with_audio:
           (d / f"{channel}{ext}").write_bytes(b"\x00" * 256)
       # 0チャンク・ready のまま終わった録音を模す
       sources_repo.update_source_status(
           ctx.conn, src.id, status=sources_repo.SourceStatus.READY, chunk_count=0
       )
       return src.id


   def test_retry_dispatches_pipeline_from_compressed_audio(client):
       nb = _create_nb(client)
       fake = _FakePipeline()
       fakevs = _FakeVectorStore()
       client.app.state.ctx.recording_pipeline = fake
       client.app.state.ctx.vector_store = fakevs

       src_id = _seed_recording(client, nb, with_audio=True, channel="mic", ext=".m4a")

       r = client.post(f"/api/notebooks/{nb}/recordings/{src_id}/retry")
       assert r.status_code == 200, r.text
       body = r.json()
       assert body["source_id"] == src_id
       assert body["status"] == "processing"

       # ベクタ削除が呼ばれた
       assert fakevs.deleted == [src_id]

       # パイプラインが再ディスパッチされ、mic 音源が Path で渡る
       assert len(fake.calls) == 1
       call = fake.calls[0]
       assert call["source_id"] == src_id
       assert call["notebook_id"] == nb
       assert isinstance(call["mic_wav"], Path)
       assert call["mic_wav"].name == "mic.m4a"
       assert call["system_wav"] is None
       assert call["transcriber"] is not None
       assert "diarizer" in call

       # status が parsing 以降へ
       src = sources_repo.get_source(client.app.state.ctx.conn, src_id)
       assert src.status in (
           sources_repo.SourceStatus.PARSING,
           sources_repo.SourceStatus.READY,
       )


   def test_retry_422_when_no_audio(client):
       nb = _create_nb(client)
       client.app.state.ctx.recording_pipeline = _FakePipeline()
       src_id = _seed_recording(client, nb, with_audio=False)

       r = client.post(f"/api/notebooks/{nb}/recordings/{src_id}/retry")
       assert r.status_code == 422, r.text


   def test_retry_rejects_non_recording_source(client):
       nb = _create_nb(client)
       client.app.state.ctx.recording_pipeline = _FakePipeline()
       ctx = client.app.state.ctx
       doc = sources_repo.create_source(
           ctx.conn, notebook_id=nb, kind="pdf", title="doc", origin="a.pdf"
       )
       r = client.post(f"/api/notebooks/{nb}/recordings/{doc.id}/retry")
       assert r.status_code == 422, r.text


   def test_retry_404_when_source_in_other_notebook(client):
       nb1 = _create_nb(client)
       nb2 = _create_nb(client)
       client.app.state.ctx.recording_pipeline = _FakePipeline()
       src_id = _seed_recording(client, nb1, with_audio=True)
       r = client.post(f"/api/notebooks/{nb2}/recordings/{src_id}/retry")
       assert r.status_code == 404, r.text
   ```

2. (失敗を確認)実行: `uv run pytest tests/integration/test_api/test_recording_retry_dispatch.py -q`
   期待する失敗: `assert 405 == 200`(`/recordings/{sid}/retry` ルート未定義 → Method Not Allowed / 404)。

3. (最小実装: 共有 dispatch ヘルパ抽出)`apps/api/routers/recordings.py` の冒頭 import に追加:
   ```python
   from apps.api.routers.audio import _resolve_audio_path
   from core.storage.chunks_repo import delete_chunks_for_source
   ```
   そして `stop_recording` の上(`_resolve_wav` の直後)へ共有ヘルパを追加:
   ```python
   def _dispatch_recording_pipeline(
       request: Request,
       background: BackgroundTasks,
       *,
       notebook_id: str,
       source_id: str,
       mic_audio,
       system_audio,
   ) -> None:
       """録音オフラインパイプラインを background task として投入する(stop / retry 共通)。

       mic_audio / system_audio は解決済みの Path | None。少なくとも一方は非 None で
       あること(呼び出し側で検証)。現行 AudioSettings と共有 transcriber/diarizer を
       流用し、source を PARSING にしてから dispatch する。
       """
       ctx = request.app.state.ctx
       a = ctx.config.audio
       model = ctx.config.ollama.default_model
       transcriber = _get_transcriber(request)
       diarizer = _get_diarizer(request)
       sources_repo.update_source_status(
           ctx.conn, source_id, status=sources_repo.SourceStatus.PARSING
       )
       background.add_task(
           ctx.recording_pipeline.run,
           source_id=source_id,
           notebook_id=notebook_id,
           mic_wav=mic_audio,
           system_wav=system_audio,
           transcriber=transcriber,
           diarizer=diarizer,
           model=model,
           diarization_enabled=(a.diarization_enabled and diarizer is not None),
           name_inference_enabled=a.name_inference_llm,
           name_threshold=a.name_threshold,
           storage_format=a.storage_format,
           storage_bitrate_kbps=a.storage_bitrate_kbps,
           keep_audio=a.keep_audio,
       )
   ```

4. (最小実装: stop_recording を共有ヘルパへ寄せる)`stop_recording` 内の L255-278(`src_id = ...` から `background.add_task(...)` まで)を以下へ置換:
   ```python
       src_id = sess.extras.get("source_id")
       _dispatch_recording_pipeline(
           request,
           background,
           notebook_id=notebook_id,
           source_id=src_id,
           mic_audio=mic_wav,
           system_audio=system_wav,
       )
   ```
   注: `mic_wav` / `system_wav` は直前で `_resolve_wav(...)` 済みのまま再利用する。`status=PARSING` への更新はヘルパ内に移ったので元の `update_source_status` 行は削除する。

5. (最小実装: retry エンドポイント追加)`recordings.py` 末尾の `live_gain` の前(または `stop_recording` の直後)へ追加:
   ```python
   @router.post("/api/notebooks/{notebook_id}/recordings/{source_id}/retry")
   async def retry_recording(
       request: Request, notebook_id: str, source_id: str, background: BackgroundTasks
   ):
       """既に変換済みの圧縮音源(.m4a/.opus/.mp3/.wav)からオフライン RAG パイプラインを
       再実行する。0チャンクや error で終わった録音の再埋め込み手段。

       チャンネル別に音源を解決し、両方欠如なら 422。既存チャンク(sqlite + ベクタ)を
       クリアして PARSING にし、stop と同じ dispatch を再利用する。
       """
       from core.exceptions import AppError

       ctx = request.app.state.ctx
       try:
           src = sources_repo.get_source(ctx.conn, source_id)
       except AppError:
           raise HTTPException(status_code=404, detail="source not found")
       if src.notebook_id != notebook_id:
           raise HTTPException(status_code=404, detail="source not in notebook")
       if src.kind != "recording":
           raise HTTPException(status_code=422, detail="source is not a recording")

       base = ctx.config.sources_dir / source_id
       mic_audio = _resolve_audio_path(base, "mic") if base.is_dir() else None
       system_audio = _resolve_audio_path(base, "system") if base.is_dir() else None
       if mic_audio is None and system_audio is None:
           raise HTTPException(status_code=422, detail="no audio to re-embed")

       # 既存チャンクをクリア(sqlite + ベクタ)
       delete_chunks_for_source(ctx.conn, source_id)
       ctx.vector_store.delete_by_source(source_id)

       _dispatch_recording_pipeline(
           request,
           background,
           notebook_id=notebook_id,
           source_id=source_id,
           mic_audio=mic_audio,
           system_audio=system_audio,
       )
       return {"source_id": source_id, "status": "processing"}
   ```
   注: `_resolve_audio_path` は圧縮音源(.m4a/.opus/.mp3)を wav より優先する(`_AUDIO_EXT_PRIORITY`)。WAV削除済みの通常運用では .m4a/.opus が解決される。

6. (パスを確認)実行: `uv run pytest tests/integration/test_api/test_recording_retry_dispatch.py -q`
   期待: 4 passed。

7. (stop 回帰確認)実行: `uv run pytest tests/integration/test_api/test_recording_stop_dispatch.py -q`
   期待: 2 passed(共有ヘルパ抽出後も stop の dispatch kwargs が不変)。

8. (コミット)
   ```
   git add apps/api/routers/recordings.py tests/integration/test_api/test_recording_retry_dispatch.py
   git commit -m "feat(api): 録音再生成 POST /recordings/{sid}/retry を追加し stop と dispatch を共有化"
   ```

### Task E.3 フロント: `Source` 型に `has_audio` を足し、再生成クライアントを追加(SvelteKit)

`lib/api/types.ts::Source` に `has_audio` を追加、`lib/api/sources.ts` に `recordingRetry` を追加(文書 `retry()` とは別経路で `/recordings/{sid}/retry` を叩く)。

**Files**
- Modify: `apps/web/src/lib/api/types.ts`
- Modify: `apps/web/src/lib/api/sources.ts`
- Test(規約): `npm run check`(0 errors)+ `npm run build`

**Interfaces**
- Consumes: `request<Source>(path, { method: 'POST' })`(既存 `./client`)
- Produces: `Source.has_audio?: boolean`
- Produces: `sourcesApi.recordingRetry(notebookId: string, sourceId: string): Promise<Source>`(`POST /api/notebooks/{nb}/recordings/{sid}/retry`)

**Steps**

1. (型追加)`apps/web/src/lib/api/types.ts` の `Source` interface、`chunk_count` の次行へ追加:
   ```ts
     chunk_count: number | null;
     has_audio?: boolean;
   ```

2. (クライアント追加)`apps/web/src/lib/api/sources.ts` の `retry` の次へ追加:
   ```ts
     retry: (notebookId: string, sourceId: string) =>
       request<Source>(`/api/notebooks/${notebookId}/sources/${sourceId}/retry`, {
         method: 'POST',
       }),
     recordingRetry: (notebookId: string, sourceId: string) =>
       request<Source>(
         `/api/notebooks/${notebookId}/recordings/${sourceId}/retry`,
         { method: 'POST' },
       ),
   ```
   注: バックエンドの retry は `{source_id, status}` を返すが、フロントは戻り値を使わず `upsertSource` で別途リフレッシュする(Task E.4)。型は `Source` のままにせず、戻りを使わないため `request<unknown>` でも良いが、既存 `retry` と揃え将来 `_to_schema` 化に備え `Source` を維持する。

3. (型チェック)実行: `cd apps/web && npm run check`
   期待: 0 errors, 0 warnings。

4. (ビルド確認)実行: `cd apps/web && npm run build`
   期待: ビルド成功(`dist/` 出力)。

5. (コミット)
   ```
   git add apps/web/src/lib/api/types.ts apps/web/src/lib/api/sources.ts
   git commit -m "feat(web): Source 型に has_audio を追加し recordingRetry クライアントを追加"
   ```

### Task E.4 フロント: 再生成ボタン(`SourceCard` / `SourcesPanel`)(SvelteKit + Playwright ゲート)

`SourceCard` に `$derived canReembed` と `RefreshCw` の「再生成」ボタンを追加(既存 retry は `status==='error'` のみ表示なのと別系統)。`SourcesPanel` に録音専用ハンドラを追加し `sourcesApi.recordingRetry` を呼び、呼出後 `upsertSource` で更新する。

**Files**
- Modify: `apps/web/src/lib/components/SourceCard.svelte`
- Modify: `apps/web/src/lib/components/SourcesPanel.svelte`
- Test(規約): `npm run check` + `npm run build` + Playwright 実機スクショ検証ゲート

**Interfaces**
- Consumes(SourceCard): `source: Source`(`has_audio`, `chunk_count`, `status`, `kind`)
- Produces(SourceCard): `onReembed: () => void` prop、`canReembed = $derived(...)` 真のとき `RefreshCw`(`aria-label="再生成"`)ボタン
- Consumes(SourcesPanel): `sourcesApi.recordingRetry`, `currentNotebookStore.upsertSource`
- Produces(SourcesPanel): `onReembed(s: Source)` ハンドラ

**Steps**

1. (SourceCard: prop 追加)`apps/web/src/lib/components/SourceCard.svelte` の `Props` interface に追加:
   ```ts
       onRetry: () => void;
       onReembed: () => void;
       onDelete: () => void;
   ```
   そして分割代入も更新:
   ```ts
     let { source, selected, onToggle, onSelect, onRetry, onReembed, onDelete }: Props = $props();
   ```

2. (SourceCard: derived 追加)`showConvStatus` の `$derived(...)` ブロックの直後へ追加:
   ```ts
     // 録音の再生成(再埋め込み)可否: 録音 && 0チャンクで ready && 音源あり。
     // error 録音は既存 retry ボタン(status==='error' で表示)が担い、Step 5 で
     // 録音時のみ recordingRetry へルーティングする。二重ボタンを避けるため
     // canReembed は error を含めず「0チャンク ready」だけを拾う。
     const canReembed = $derived(
       source.kind === 'recording' &&
         (source.chunk_count ?? 0) === 0 &&
         source.status === 'ready' &&
         source.has_audio === true,
     );
   ```

3. (SourceCard: ボタン追加)`.actions` 内、`status==='error'` の retry ブロックの直後・削除ボタンの前へ追加:
   ```svelte
       {#if canReembed}
         <button class="icon" onclick={onReembed} aria-label="再生成" title="再生成">
           <RefreshCw size="14" />
         </button>
       {/if}
   ```
   注: `RefreshCw` は既に import 済み(L3)。`canReembed` は error を含めない(上記)ので、error 録音では**既存 retry ボタンのみ**が出る(二重表示しない)。その既存 retry を録音時は `recordingRetry` にルーティングする(Step 5)。よって「0チャンク ready」=本ボタン、「error」=既存 retry ボタン、と役割が一意になり、Playwright ゲートでどちらの導線も曖昧さなく検証できる。

4. (SourcesPanel: ハンドラ追加)`apps/web/src/lib/components/SourcesPanel.svelte` の `onRetry` 関数の直後へ追加:
   ```ts
     async function onReembed(s: Source) {
       try {
         await sourcesApi.recordingRetry(notebookId, s.id);
         // retry は {source_id,status} を返すため Source 全体を取り直して反映する。
         const fresh = await sourcesApi.list(notebookId);
         const updated = fresh.find((x) => x.id === s.id);
         if (updated) currentNotebookStore.upsertSource(updated);
         pushToast('再生成を開始しました', 'info');
       } catch (e) {
         pushToast(e instanceof Error ? e.message : String(e), 'error');
       }
     }
   ```

5. (SourcesPanel: error 録音を recordingRetry へルーティング)`onRetry` を録音判定付きへ変更。既存 `onRetry`:
   ```ts
     async function onRetry(s: Source) {
       try {
         const updated = await sourcesApi.retry(notebookId, s.id);
         currentNotebookStore.upsertSource(updated);
         pushToast('再試行を開始しました', 'info');
       } catch (e) {
         pushToast(e instanceof Error ? e.message : String(e), 'error');
       }
     }
   ```
   を以下へ置換(録音は文書 retry に流さず recordingRetry へ委譲):
   ```ts
     async function onRetry(s: Source) {
       if (s.kind === 'recording') {
         await onReembed(s);
         return;
       }
       try {
         const updated = await sourcesApi.retry(notebookId, s.id);
         currentNotebookStore.upsertSource(updated);
         pushToast('再試行を開始しました', 'info');
       } catch (e) {
         pushToast(e instanceof Error ? e.message : String(e), 'error');
       }
     }
   ```

6. (SourcesPanel: SourceCard へ prop 配線)`<SourceCard ...>` に `onReembed` を追加:
   ```svelte
         <SourceCard
           source={s}
           selected={currentNotebookStore.selectedSourceIds.has(s.id)}
           onToggle={() => currentNotebookStore.toggleSelected(s.id)}
           onSelect={() => onSourceSelect(s.id)}
           onRetry={() => onRetry(s)}
           onReembed={() => onReembed(s)}
           onDelete={() => onDelete(s)}
         />
   ```

7. (型チェック)実行: `cd apps/web && npm run check`
   期待: 0 errors, 0 warnings。

8. (ビルド確認)実行: `cd apps/web && npm run build`
   期待: ビルド成功。

9. (コミット)
   ```
   git add apps/web/src/lib/components/SourceCard.svelte apps/web/src/lib/components/SourcesPanel.svelte
   git commit -m "feat(web): 録音再生成ボタンを SourceCard に追加し SourcesPanel から recordingRetry を呼ぶ"
   ```

10. (Playwright 実機スクショ検証ゲート — コントローラが実行)以下を目視確認(自動テストGREENのみでのPASS禁止):
    - 0チャンク・`ready`・音源ありの録音ソースに「再生成」ボタン(`RefreshCw`)が出ること。
    - 音源無し録音(`has_audio===false`)ではボタンが出ないこと。
    - ボタン押下 → 変換ステップ(`RecordingConvStatus`)が進行 → チャンク生成 → 引用可能になること。
    - error 録音で retry アイコン押下が `recordingRetry` 経由(文書 retry に流れない)で再生成されること。
```

---

## #7 ソース全文ビュー (Full-text source viewer)

> ブランチ前提: `feature/rag-ux-improvements`(master直接編集禁止)。本機能のバックエンドは実 pytest、フロント(Svelte 5 runes)は `npm run check` 0件 + `npm run build` 成功 + 末尾の Playwright 実機スクショ検証ゲート(コントローラ実行)で判定する。

---

### Task G.1 — `list_chunks_for_source` を `chunks_repo` に追加(ord 昇順)

録音ソースの全文トランスクリプトを `ord ASC` で取り出す純粋リポジトリ関数。content エンドポイントの録音分岐がこれを消費する。

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\core\storage\chunks_repo.py`
- Test: `E:\00_Git\10_NotebookOllama\tests\integration\test_chunks_repo.py`(既存ファイルへ追記)

**Interfaces**
- Produces: `def list_chunks_for_source(conn: sqlite3.Connection, source_id: str) -> list[ChunkRecord]` — `WHERE source_id = ? ORDER BY ord ASC`。各 `ChunkRecord` は既存 `from_row` 経由(`ord/text/start_ms/end_ms/speaker/page/heading_path` を保持)。
- Consumes: 既存 `ChunkRecord.from_row(row: sqlite3.Row)`。

**Steps**

1. 失敗するテストを `test_chunks_repo.py` の末尾に追記する。
   ```python


def test_list_chunks_for_source_orders_by_ord_asc(tmp_path):
    from core.storage.chunks_repo import list_chunks_for_source

    conn, nb, src = _ctx(tmp_path)
    # insert out of ord order
    insert_chunks(conn, [_chunk(nb.id, src.id, 2, "third")])
    insert_chunks(conn, [_chunk(nb.id, src.id, 0, "first")])
    insert_chunks(conn, [_chunk(nb.id, src.id, 1, "second")])

    fetched = list_chunks_for_source(conn, src.id)
    assert [c.ord for c in fetched] == [0, 1, 2]
    assert [c.text for c in fetched] == ["first", "second", "third"]


def test_list_chunks_for_source_scopes_to_source(tmp_path):
    from core.storage.chunks_repo import list_chunks_for_source
    from core.storage.sources_repo import create_source

    conn, nb, src = _ctx(tmp_path)
    other = create_source(conn, notebook_id=nb.id, kind="md", content_hash="h2")
    insert_chunks(conn, [_chunk(nb.id, src.id, 0, "mine")])
    insert_chunks(conn, [_chunk(nb.id, other.id, 0, "theirs")])

    fetched = list_chunks_for_source(conn, src.id)
    assert [c.text for c in fetched] == ["mine"]
   ```

2. テストを実行し、失敗(`ImportError: cannot import name 'list_chunks_for_source'`)を確認する。
   ```
   uv run pytest tests/integration/test_chunks_repo.py -q
   ```
   期待: 新規2件が collection/import エラーで赤、既存3件は無関係。

3. `chunks_repo.py` の `delete_chunks_for_source` の直前(`get_chunks_by_ids` の後)に関数を追加する。
   ```python
def list_chunks_for_source(conn: sqlite3.Connection, source_id: str) -> list[ChunkRecord]:
    rows = conn.execute(
        "SELECT * FROM chunks WHERE source_id = ? ORDER BY ord ASC", (source_id,)
    ).fetchall()
    return [ChunkRecord.from_row(row) for row in rows]
   ```

4. テストを再実行し、緑を確認する。
   ```
   uv run pytest tests/integration/test_chunks_repo.py -q
   ```
   期待: 5 passed。

5. コミットする。
   ```
   git add core/storage/chunks_repo.py tests/integration/test_chunks_repo.py
   git commit -m "feat(storage): list_chunks_for_source を追加(ord昇順で録音全文を取得)"
   ```

---

### Task G.2 — content レスポンススキーマを追加

content エンドポイントの返却型を Pydantic で定義する(文書=sections / 録音=segments の判別共用体)。

**Files**
- Create: `E:\00_Git\10_NotebookOllama\apps\api\schemas\source_content.py`
- Test: なし(スキーマ単体テストは不要。G.3 のエンドポイントテストが間接検証)

**Interfaces**
- Produces:
  - `class DocumentSection(BaseModel)`: `heading_path: str | None`, `page: int | None`, `text: str`
  - `class RecordingSegment(BaseModel)`: `ord: int`, `text: str`, `start_ms: int | None`, `end_ms: int | None`, `speaker: str | None`
  - `class DocumentContent(BaseModel)`: `kind: Literal["document"]`, `sections: list[DocumentSection]`
  - `class RecordingContent(BaseModel)`: `kind: Literal["recording"]`, `segments: list[RecordingSegment]`

**Steps**

1. スキーマファイルを新規作成する。
   ```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class DocumentSection(BaseModel):
    heading_path: str | None = None
    page: int | None = None
    text: str


class RecordingSegment(BaseModel):
    ord: int
    text: str
    start_ms: int | None = None
    end_ms: int | None = None
    speaker: str | None = None


class DocumentContent(BaseModel):
    kind: Literal["document"] = "document"
    sections: list[DocumentSection]


class RecordingContent(BaseModel):
    kind: Literal["recording"] = "recording"
    segments: list[RecordingSegment]
   ```

2. import が通ることだけ確認する(構文/型の早期検出)。
   ```
   uv run python -c "import apps.api.schemas.source_content as m; print(m.DocumentContent, m.RecordingContent)"
   ```
   期待: 2クラスが表示され例外なし。

3. コミットする。
   ```
   git add apps/api/schemas/source_content.py
   git commit -m "feat(api): ソース全文ビュー用 content レスポンススキーマを追加"
   ```

---

### Task G.3 — `GET /sources/{sid}/content` エンドポイント(文書再パース + 録音 segments)

文書系ソースは保存済み元バイト列を `core/ingestion/parsers` で再パースして忠実な `sections` を返す。録音は `list_chunks_for_source` を `segments` に整形して返す。パーサ再実行コストは表示毎に発生する(初期は都度パースで許容、計測して必要ならキャッシュ追加)。

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\apps\api\routers\sources.py`
- Test: `E:\00_Git\10_NotebookOllama\tests\integration\test_api\test_source_content_api.py`(新規)

**Interfaces**
- Produces (HTTP): `GET /api/notebooks/{notebook_id}/sources/{source_id}/content`
  - 文書系 (`src.kind` ∈ {`pdf,markdown,txt,docx,pptx,xlsx,web`}) → `{"kind":"document","sections":[{"heading_path":str|None,"page":int|None,"text":str}, ...]}`
  - `recording` → `{"kind":"recording","segments":[{"ord":int,"text":str,"start_ms":int|None,"end_ms":int|None,"speaker":str|None}, ...]}`
  - ノートブック不一致 / ソース未発見 → `STORAGE_NOT_FOUND`、文書の元ファイルがディスク上に無い → `INPUT_INVALID`
- Consumes:
  - `core.ingestion.parsers.get_parser(kind) -> Parser`、`Parser.parse_bytes(data, source_hint=...) -> ParsedDocument`(各 `ParsedSection`: `text/page/heading_path: list[str]`)
  - `core.storage.chunks_repo.list_chunks_for_source(conn, source_id) -> list[ChunkRecord]`
  - 既存モジュール内: `_EXT_BY_KIND`, `sources_repo.get_source`

**Steps**

1. 失敗するテストファイルを新規作成する(文書再パース + 録音 segments + 不一致 404)。
   ```python
import io

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        ctx = c.app.state.ctx

        class NoopPipeline:
            async def run(self, *, source_id, kind, data):
                from core.storage.sources_repo import SourceStatus, update_source_status

                update_source_status(ctx.conn, source_id, status=SourceStatus.READY, chunk_count=0)

        ctx.pipeline = NoopPipeline()
        yield c


def _create_nb(client) -> str:
    return client.post("/api/notebooks", json={"name": "N"}).json()["id"]


def test_content_document_reparses_faithfully(client):
    nb = _create_nb(client)
    md = b"# Title\n\nfirst para.\n\n## Sub\n\nsecond para.\n"
    files = {"file": ("doc.md", io.BytesIO(md), "text/markdown")}
    sid = client.post(f"/api/notebooks/{nb}/sources", files=files).json()["id"]

    r = client.get(f"/api/notebooks/{nb}/sources/{sid}/content")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "document"
    texts = [s["text"] for s in body["sections"]]
    assert any("first para." in t for t in texts)
    assert any("second para." in t for t in texts)
    # heading structure is preserved (joined with " > ")
    assert any(s["heading_path"] and "Sub" in s["heading_path"] for s in body["sections"])


def test_content_recording_returns_ordered_segments(client):
    nb = _create_nb(client)
    ctx = client.app.state.ctx
    from core.storage.sources_repo import create_source
    from core.storage.chunks_repo import ChunkRecord, insert_chunks

    src = create_source(
        ctx.conn, notebook_id=nb, kind="recording",
        origin="talk.mp3", content_hash="rec_content_test",
    )
    sid = src.id
    insert_chunks(ctx.conn, [
        ChunkRecord(id="1" * 26, source_id=sid, notebook_id=nb, ord=1,
                    page=None, heading_path=None, text="second", token_count=1,
                    start_ms=2000, end_ms=3000, speaker="相手1"),
        ChunkRecord(id="0" * 26, source_id=sid, notebook_id=nb, ord=0,
                    page=None, heading_path=None, text="first", token_count=1,
                    start_ms=0, end_ms=1000, speaker="あなた"),
    ])

    r = client.get(f"/api/notebooks/{nb}/sources/{sid}/content")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "recording"
    assert [s["ord"] for s in body["segments"]] == [0, 1]
    assert body["segments"][0] == {
        "ord": 0, "text": "first", "start_ms": 0, "end_ms": 1000, "speaker": "あなた",
    }
    assert body["segments"][1]["speaker"] == "相手1"


def test_content_rejects_source_from_other_notebook(client):
    nb1 = _create_nb(client)
    nb2 = _create_nb(client)
    files = {"file": ("a.md", io.BytesIO(b"# A"), "text/markdown")}
    sid = client.post(f"/api/notebooks/{nb1}/sources", files=files).json()["id"]
    r = client.get(f"/api/notebooks/{nb2}/sources/{sid}/content")
    assert r.status_code == 404
   ```

2. テストを実行し、失敗(404 ルート未定義のため文書/録音テストが赤、または `405/404`)を確認する。
   ```
   uv run pytest tests/integration/test_api/test_source_content_api.py -q
   ```
   期待: 3件すべて赤(エンドポイント未実装)。

3. `sources.py` の import に content スキーマ・パーサ・録音リポジトリを追加する。`from core.storage.chunks_repo import delete_chunks_for_source` の行を次の通り拡張する。
   ```python
from core.storage.chunks_repo import delete_chunks_for_source, list_chunks_for_source
   ```
   さらにファイル先頭の import 群(`from core.storage import notebooks_repo, sources_repo` の直後)に追記する。
   ```python
from apps.api.schemas.source_content import (
    DocumentContent,
    DocumentSection,
    RecordingContent,
    RecordingSegment,
)
from core.ingestion.parsers import get_parser
   ```

4. 文書系判定の定数を `_EXT_BY_KIND` の定義直後に追加する。
   ```python
# Document-kind sources store a flat original file (sources_dir/<id><ext>) and
# are re-parsed on demand. "recording" stores per-channel audio + chunks instead.
_DOCUMENT_KINDS = frozenset(_EXT_BY_KIND.keys())
   ```

5. content エンドポイントを `get_chunk` の直後(`retry_source` の直前)に追加する。
   ```python
@router.get(
    "/{notebook_id}/sources/{source_id}/content",
    response_model=DocumentContent | RecordingContent,
)
async def get_source_content(
    request: Request, notebook_id: str, source_id: str
) -> DocumentContent | RecordingContent:
    """Return faithful full content for a source.

    Documents are re-parsed from their stored original bytes (cost is paid on
    each view; cache later if measured). Recordings return their generated
    transcript chunks ordered by ``ord``.
    """
    ctx = request.app.state.ctx
    src = sources_repo.get_source(ctx.conn, source_id)
    if src.notebook_id != notebook_id:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "source not in notebook")

    if src.kind == "recording":
        segments = [
            RecordingSegment(
                ord=c.ord,
                text=c.text,
                start_ms=c.start_ms,
                end_ms=c.end_ms,
                speaker=c.speaker,
            )
            for c in list_chunks_for_source(ctx.conn, source_id)
        ]
        return RecordingContent(segments=segments)

    if src.kind not in _DOCUMENT_KINDS:
        raise AppError(
            ErrorCode.INGESTION_UNSUPPORTED_KIND,
            f"no full-content view for kind={src.kind}",
        )

    ext = _EXT_BY_KIND.get(src.kind, ".bin")
    source_path = ctx.config.sources_dir / f"{src.id}{ext}"
    if not source_path.exists():
        raise AppError(
            ErrorCode.INPUT_INVALID,
            "original source data not found on disk",
            remediation="re-upload the file",
        )
    data = source_path.read_bytes()
    parser = get_parser(src.kind)
    doc = parser.parse_bytes(data, source_hint=src.origin)
    sections = [
        DocumentSection(
            heading_path=" > ".join(s.heading_path) if s.heading_path else None,
            page=s.page,
            text=s.text,
        )
        for s in doc.sections
    ]
    return DocumentContent(sections=sections)
   ```

6. テストを再実行し、緑を確認する。
   ```
   uv run pytest tests/integration/test_api/test_source_content_api.py -q
   ```
   期待: 3 passed。

7. 回帰確認(既存ソース系テストを壊していないこと)。
   ```
   uv run pytest tests/integration/test_api/test_sources_api.py tests/integration/test_chunks_repo.py -q
   ```
   期待: すべて緑。

8. コミットする。
   ```
   git add apps/api/routers/sources.py tests/integration/test_api/test_source_content_api.py
   git commit -m "feat(api): GET /sources/{id}/content を追加(文書再パース/録音segments)"
   ```

---

### Task G.4 — フロント API クライアントに `getSourceContent` + 型を追加

`source_outline.ts` に content 取得関数と判別共用体型を追加する(単体は vitest 対象外の薄い fetch ラッパなので、`npm run check` の型整合で担保)。

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\api\source_outline.ts`

**Interfaces**
- Produces:
  - `interface DocumentSectionContent { heading_path: string | null; page: number | null; text: string }`
  - `interface RecordingSegmentContent { ord: number; text: string; start_ms: number | null; end_ms: number | null; speaker: string | null }`
  - `type SourceContent = { kind: 'document'; sections: DocumentSectionContent[] } | { kind: 'recording'; segments: RecordingSegmentContent[] }`
  - `sourceDetailApi.getSourceContent(notebookId, sourceId) => Promise<SourceContent>`
- Consumes: 既存 `request<T>` from `./client`

**Steps**

1. 型と関数を `source_outline.ts` に追加する。`ChunkDetail` インターフェース定義の直後に型を挿入する。
   ```typescript
export interface DocumentSectionContent {
  heading_path: string | null;
  page: number | null;
  text: string;
}

export interface RecordingSegmentContent {
  ord: number;
  text: string;
  start_ms: number | null;
  end_ms: number | null;
  speaker: string | null;
}

export type SourceContent =
  | { kind: 'document'; sections: DocumentSectionContent[] }
  | { kind: 'recording'; segments: RecordingSegmentContent[] };
   ```

2. `sourceDetailApi` オブジェクトに `getSourceContent` メソッドを追加する。`getChunk` メソッドの直後(オブジェクト末尾 `};` の前)に追記する。
   ```typescript
  getSourceContent: (notebookId: string, sourceId: string) =>
    request<SourceContent>(
      `/api/notebooks/${notebookId}/sources/${sourceId}/content`,
    ),
   ```
   結果として `sourceDetailApi` は次の形になる。
   ```typescript
export const sourceDetailApi = {
  getChunk: (notebookId: string, sourceId: string, chunkId: string) =>
    request<ChunkDetail>(
      `/api/notebooks/${notebookId}/sources/${sourceId}/chunks/${chunkId}`,
    ),
  getSourceContent: (notebookId: string, sourceId: string) =>
    request<SourceContent>(
      `/api/notebooks/${notebookId}/sources/${sourceId}/content`,
    ),
};
   ```

3. 型チェックを実行する。
   ```
   cd apps/web && npm run check
   ```
   期待: 0 errors / 0 warnings(新規型がエクスポートされ未使用警告なし)。

4. コミットする。
   ```
   git add apps/web/src/lib/api/source_outline.ts
   git commit -m "feat(web): source API に getSourceContent と content 型を追加"
   ```

---

### Task G.5 — 共有 `<audio>` プレーヤーを `SharedAudioPlayer.svelte` に抽出(行クリックでシーク)

録音全文ビューはトランスクリプト1個につき(channel別に)プレーヤーを1つ共有し、行クリックでその `start_ms` にシークする。`AudioCitationPlayer.svelte` のロジックを一般化した再利用コンポーネントを切り出す(`AudioCitationPlayer` 自体は引用単一チャンク経路で不変のまま残す)。

**Files**
- Create: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\SharedAudioPlayer.svelte`

**Interfaces**
- Produces (Svelte component):
  - Props: `notebookId: string`, `sourceId: string`, `channel: 'mic' | 'system'`
  - Exposed via `bindable` ref-method: `seekToMs(ms: number): void`(親が行クリック時に呼ぶ。再生中なら継続、停止中はシークのみ)
  - 自前 transport UI(再生/一時停止、シークバー、現在時刻/総時間)を持つ。`endMs` バウンドの「この箇所を再生」概念は持たない(全文プレーヤーは自由再生)。
- Consumes: `/api/notebooks/{notebookId}/sources/{sourceId}/audio?channel={channel}`(既存 audio ルート、Range対応済み)

**Steps**

1. コンポーネントを新規作成する。`AudioCitationPlayer` の transport ロジックを基に、`startMs/endMs/excerpt` を除去し、`channel` を prop 化、`seekToMs` を `$bindable` 関数として公開する。
   ```svelte
<script lang="ts">
  interface Props {
    notebookId: string;
    sourceId: string;
    channel: 'mic' | 'system';
    // Bindable ref so the parent transcript can drive seeks on line-click.
    seek?: (ms: number) => void;
  }
  let { notebookId, sourceId, channel, seek = $bindable() }: Props = $props();

  let src = $derived(
    `/api/notebooks/${notebookId}/sources/${sourceId}/audio?channel=${channel}`,
  );

  let audioEl = $state<HTMLAudioElement | null>(null);
  let playing = $state(false);
  let currentTime = $state(0);
  let duration = $state(0);
  let metadataLoaded = $state(false);

  function formatTime(seconds: number): string {
    if (!Number.isFinite(seconds) || seconds < 0) return '00:00';
    const total = Math.floor(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  // Publish the seek handler to the parent. Seeking does not auto-play; if
  // already playing, the head moves and playback continues from there.
  seek = (ms: number) => {
    if (!audioEl) return;
    if (!metadataLoaded) {
      // metadata not ready yet: defer one tick by setting then re-applying
      audioEl.currentTime = ms / 1000;
      return;
    }
    audioEl.currentTime = ms / 1000;
    currentTime = audioEl.currentTime;
    if (audioEl.paused) {
      void audioEl.play();
    }
  };

  function onLoadedMetadata() {
    if (!audioEl) return;
    metadataLoaded = true;
    duration = audioEl.duration;
  }
  function onTimeUpdate() {
    if (!audioEl) return;
    currentTime = audioEl.currentTime;
  }
  function onPlay() {
    playing = true;
  }
  function onPause() {
    playing = false;
  }
  function onEnded() {
    playing = false;
  }

  function togglePlay() {
    if (!audioEl) return;
    if (audioEl.paused) {
      void audioEl.play();
    } else {
      audioEl.pause();
    }
  }

  function onSeek(e: Event) {
    if (!audioEl) return;
    const value = Number((e.currentTarget as HTMLInputElement).value);
    audioEl.currentTime = value;
    currentTime = value;
  }
</script>

<div class="player">
  <audio
    bind:this={audioEl}
    {src}
    preload="metadata"
    onloadedmetadata={onLoadedMetadata}
    ontimeupdate={onTimeUpdate}
    onplay={onPlay}
    onpause={onPause}
    onended={onEnded}
  ></audio>

  <div class="row1">
    <button
      class="play"
      type="button"
      onclick={togglePlay}
      aria-label={playing ? '一時停止' : '再生'}
    >
      {playing ? '⏸' : '▶'}
    </button>
    <input
      class="track"
      type="range"
      min="0"
      max={duration || 0}
      step="0.01"
      value={currentTime}
      oninput={onSeek}
      aria-label="シーク"
    />
    <span class="ttime">{formatTime(currentTime)} / {formatTime(duration)}</span>
  </div>
</div>

<style>
  .player {
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-3);
    background: var(--color-bg);
    margin-bottom: var(--space-3);
  }
  .row1 {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }
  .play {
    width: 34px;
    height: 34px;
    border-radius: 50%;
    border: none;
    background: var(--color-accent);
    color: #fff;
    display: grid;
    place-items: center;
    flex: none;
    font-size: 13px;
    line-height: 1;
  }
  .play:hover {
    background: var(--color-accent-hover);
  }
  .track {
    flex: 1;
    min-width: 0;
    height: 6px;
    accent-color: var(--color-accent);
    cursor: pointer;
  }
  .ttime {
    font-size: 11px;
    color: var(--color-fg-muted);
    font-family: var(--font-mono);
    flex: none;
  }
</style>
   ```

2. 型チェックを実行する。
   ```
   cd apps/web && npm run check
   ```
   期待: 0 errors(`$bindable` 関数 prop の型が通る。未参照警告は G.6 で消費するため、ここで残る場合は G.6 まで保留)。

3. コミットする。
   ```
   git add apps/web/src/lib/components/SharedAudioPlayer.svelte
   git commit -m "feat(web): 録音全文ビュー用の共有AudioプレーヤーをSharedAudioPlayerに抽出"
   ```

---

### Task G.6 — `SourceViewer.svelte` で全文ビューを描画(文書 sections / 録音 transcript)

`resolvedSourceId` があり `selectedChunkId === null` のとき `getSourceContent` を取得し、文書はセクション順、録音はトランスクリプト行リスト(話者チップ + `mm:ss` + 本文、channel別の共有プレーヤー上部 + 行クリックでシーク)を描画する。既存の単一チャンク引用経路は不変のまま残す。

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\SourceViewer.svelte`

**Interfaces**
- Consumes: `sourceDetailApi.getSourceContent` (G.4)、`SharedAudioPlayer` (G.5, `seek` バインド)、既存 `formatTimecode`、`currentNotebookStore.sources`
- Produces: なし(UI のみ)

**Steps**

1. import に新 API 型と共有プレーヤーを追加する。`import { sourceDetailApi, type ChunkDetail } from '$lib/api/source_outline';` を次へ差し替える。
   ```typescript
  import {
    sourceDetailApi,
    type ChunkDetail,
    type SourceContent,
    type RecordingSegmentContent,
  } from '$lib/api/source_outline';
   ```
   さらに `import AudioCitationPlayer from './AudioCitationPlayer.svelte';` の直後に追記する。
   ```typescript
  import SharedAudioPlayer from './SharedAudioPlayer.svelte';
   ```

2. content 用の state を、既存 `let error = $state<string | null>(null);` の直後に追加する。
   ```typescript
  let content = $state<SourceContent | null>(null);
  let contentLoading = $state(false);
  let contentError = $state<string | null>(null);
  // Bindable seek handlers published by the per-channel shared players.
  let seekMic = $state<((ms: number) => void) | undefined>(undefined);
  let seekSystem = $state<((ms: number) => void) | undefined>(undefined);
   ```

3. 全文取得 `$effect` を、既存の単一チャンク取得 `$effect`(`sourceDetailApi.getChunk` を呼ぶブロック)の直後に追加する。`selectedChunkId === null` かつ `resolvedSourceId` があるときだけ走らせる。
   ```typescript
  $effect(() => {
    const cid = selectedChunkId;
    const sid = resolvedSourceId;
    if (cid || !sid) {
      content = null;
      return;
    }
    contentLoading = true;
    contentError = null;
    sourceDetailApi
      .getSourceContent(notebookId, sid)
      .then((c) => {
        content = c;
      })
      .catch((e) => {
        contentError = e instanceof Error ? e.message : String(e);
      })
      .finally(() => {
        contentLoading = false;
      });
  });
   ```

4. 録音セグメントの channel 判定と行クリックヘルパを、`sourceMeta` の `$derived` の直後に追加する(`AudioCitationPlayer` と同じ規約: `あなた`=mic、それ以外=system)。
   ```typescript
  function segChannel(speaker: string | null): 'mic' | 'system' {
    return speaker === 'あなた' ? 'mic' : 'system';
  }

  function seekToSegment(seg: RecordingSegmentContent) {
    if (seg.start_ms == null) return;
    const fn = segChannel(seg.speaker) === 'mic' ? seekMic : seekSystem;
    fn?.(seg.start_ms);
  }

  // Which channels actually appear, so we only mount players we need.
  let recordingChannels = $derived.by<Array<'mic' | 'system'>>(() => {
    if (content?.kind !== 'recording') return [];
    const set = new Set<'mic' | 'system'>();
    for (const s of content.segments) set.add(segChannel(s.speaker));
    return [...set];
  });
   ```

5. テンプレートに全文ビューの分岐を追加する。既存テンプレートの単一チャンク `{:else if chunk}` ブロック(`</div>` で閉じる `.chunk`)の直後、`.viewer` を閉じる `</div>` の前に挿入する。
   ```svelte
  {:else if selectedChunkId === null && resolvedSourceId}
    {#if contentLoading}
      <div class="state"><Spinner /> 読み込み中…</div>
    {:else if contentError}
      <div class="state err">エラー: {contentError}</div>
    {:else if content?.kind === 'document'}
      <div class="fulltext">
        {#each content.sections as section, i (i)}
          <section class="doc-section">
            {#if section.heading_path}
              <div class="path">{section.heading_path}</div>
            {/if}
            {#if section.page}
              <div class="page">p.{section.page}</div>
            {/if}
            <pre class="text">{section.text}</pre>
          </section>
        {/each}
      </div>
    {:else if content?.kind === 'recording'}
      <div class="fulltext">
        {#if recordingChannels.includes('mic')}
          <SharedAudioPlayer
            {notebookId}
            sourceId={resolvedSourceId}
            channel="mic"
            bind:seek={seekMic}
          />
        {/if}
        {#if recordingChannels.includes('system')}
          <SharedAudioPlayer
            {notebookId}
            sourceId={resolvedSourceId}
            channel="system"
            bind:seek={seekSystem}
          />
        {/if}
        <ul class="transcript">
          {#each content.segments as seg (seg.ord)}
            <li>
              <button
                type="button"
                class="line"
                onclick={() => seekToSegment(seg)}
                disabled={seg.start_ms == null}
              >
                {#if seg.speaker}
                  <span
                    class="spk-chip"
                    style="background:{seg.speaker === 'あなた' ? 'var(--color-accent)' : '#16a34a'}"
                    >● {seg.speaker}</span
                  >
                {/if}
                {#if seg.start_ms != null}
                  <span class="tc">{formatTimecode(seg.start_ms)}</span>
                {/if}
                <span class="utt">{seg.text}</span>
              </button>
            </li>
          {/each}
        </ul>
      </div>
    {/if}
  {/if}
   ```

6. スタイルを `<style>` 末尾(`.text { … }` ブロックの後、`</style>` の前)に追加する。
   ```css
  .fulltext {
    border-top: 1px solid var(--color-border);
    padding-top: var(--space-3);
  }
  .doc-section {
    margin-bottom: var(--space-3);
  }
  .transcript {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .transcript li {
    margin-bottom: var(--space-1);
  }
  .line {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    width: 100%;
    text-align: left;
    background: none;
    border: none;
    border-radius: var(--radius-sm);
    padding: var(--space-2);
    cursor: pointer;
    font: inherit;
    color: inherit;
  }
  .line:hover:not(:disabled) {
    background: var(--color-bg-elevated);
  }
  .line:disabled {
    cursor: default;
  }
  .spk-chip {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    font-size: 11px;
    font-weight: 600;
    border-radius: 999px;
    padding: 2px 9px;
    color: #fff;
    flex: none;
  }
  .tc {
    font-size: 11px;
    color: var(--color-fg-muted);
    font-family: var(--font-mono);
    flex: none;
  }
  .utt {
    font-size: 13px;
    line-height: 1.6;
  }
   ```

7. 型チェックを実行する。
   ```
   cd apps/web && npm run check
   ```
   期待: 0 errors / 0 warnings(G.5 で残っていた `SharedAudioPlayer` 未参照も解消)。

8. 本番ビルドが通ることを確認する。
   ```
   cd apps/web && npm run build
   ```
   期待: `apps/web/dist/` 出力、エラーなし。

9. コミットする。
   ```
   git add apps/web/src/lib/components/SourceViewer.svelte
   git commit -m "feat(web): SourceViewer にソース全文ビュー(文書sections/録音transcript+共有プレーヤー)を追加"
   ```

10. **Playwright 実機スクショ検証ゲート(コントローラ実行・GUI変更のため必須)**:
    - 文書ソースをサイドバーでクリック → 右ビューアに見出し/ページ付きの忠実全文が順序通り表示されることをスクショ確認。
    - 録音ソースをクリック → 上部に channel別共有プレーヤー、下に「話者チップ + `mm:ss` + 本文」のトランスクリプト行リストが ord 順で表示されることをスクショ確認。
    - 任意の行をクリック → 該当 channel のプレーヤーがその `start_ms` 秒へシークし再生が始まることを確認(停止中クリックで再生開始、別行クリックで頭出し移動)。
    - 引用クリック(`selectedChunkId` 非 null)の単一チャンク表示が従来通り動くこと(回帰)を確認。
    - 自動テスト GREEN のみでの PASS は禁止。スクショ証跡を残して判定する。

---

### Task G.7 — 全文ビュー機能の回帰スイート確認

本機能で触れた層(storage / api / web)の既存テストを横断実行し、202件ベースラインを壊していないことを確認する。

**Files**
- Test: 既存スイート全体(新規ファイル変更なし)

**Steps**

1. バックエンド全体を実行する。
   ```
   uv run pytest -q
   ```
   期待: 既存 + 新規(G.1 の2件、G.3 の3件)すべて緑、ollama マーク分はスキップ。

2. フロント型チェックとビルドを最終確認する。
   ```
   cd apps/web && npm run check && npm run build
   ```
   期待: 0 errors、`dist/` 生成。

3. 緑が揃ったことを確認したうえで、この機能ブランチの作業を完了とする(マージ判断はコントローラ)。回帰のためのコード変更が発生した場合のみ、該当ファイルを `git add` して `fix(...)` でコミットする。
```

Key files I read and used (all absolute):
- `E:\00_Git\10_NotebookOllama\docs\specs\2026-06-19-rag-ux-improvements-design.md` (§2 row #7 + §3 #7 — fixed decisions)
- `E:\00_Git\10_NotebookOllama\apps\api\routers\sources.py` (`_EXT_BY_KIND`, `get_chunk`, `retry_source`, `_to_schema`)
- `E:\00_Git\10_NotebookOllama\core\ingestion\parsers\{__init__,base,markdown,web}.py` and `core\ingestion\types.py` — parser interface is `get_parser(kind).parse_bytes(data, source_hint=...) -> ParsedDocument` with `sections:[ParsedSection(text, page, heading_path: list[str])]`
- `E:\00_Git\10_NotebookOllama\core\ingestion\pipeline.py` — confirms reuse pattern (`get_parser` + `" > ".join(heading_path)`)
- `E:\00_Git\10_NotebookOllama\core\storage\chunks_repo.py` — `ChunkRecord.from_row`, insert pattern
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\{SourceViewer,AudioCitationPlayer}.svelte`, `apps\web\src\lib\api\source_outline.ts`, `apps\api\routers\audio.py` (channel `mic`/`system` rule: `あなた`=mic)
- Test fixture patterns from `tests\integration\test_chunks_repo.py`, `tests\integration\test_get_chunk_timecode.py`, `tests\integration\test_api\test_sources_api.py`

Two notes for the engineer: (1) `src.kind` for documents is already the parser key (`pdf/markdown/txt/docx/pptx/xlsx/web`), so `get_parser(src.kind)` works directly — `web` maps to `.html` via `_EXT_BY_KIND` and parses with the `web`/trafilatura parser. (2) The re-parse cost is paid per view (acceptable per spec §3 #7; cache later if measured).

# Ollama モデル選択(LLM/埋め込み)切替 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ollama のモデルをチャットLLM/埋め込みに分類し、チャットLLMを全体既定+ノートブックごとに、埋め込みを再インデックス付きで切り替えられるようにする。

**Architecture:** バックエンドは FastAPI(apps/api)+純ドメイン core/。モデル分類は /api/show の capabilities を一次情報+名前フォールバック。チャットLLM既定は settings.json 永続化+起動時 apply_overrides で反映(リクエスト毎に cfg を読むため即時)。埋め込み切替は collection 再作成+全チャンク再埋め込み(SSE進捗)で、embedding_model と collection 次元を常に一体で動かし破綻状態を構造的に防ぐ。フロントは SvelteKit(Svelte 5 runes)。

**Tech Stack:** Python(FastAPI, pydantic, qdrant-client, httpx)/ SvelteKit + TypeScript / Ollama / Qdrant(local)/ SQLite。

## Global Constraints

- master 直接編集禁止。ブランチは `feature/model-selection`(`feature/recording-naming` の上に積む)。
- コミットメッセージに Co-Authored-By trailer を付けない。
- 新規ランタイム依存を追加しない(分類・プローブは既存 OllamaClient/Gateway を流用)。
- GUI 描画に影響する変更は自動テスト GREEN だけで PASS としない。最終 Playwright 実機スクリーンショット検証ゲートを必須とする。
- 既存テストを壊さない。新規バックエンドはユニット/統合テストを伴う(TDD)。
- テスト規約(finding 17): `pyproject.toml` で `asyncio_mode = "auto"` 済みのため、async テスト関数の `@pytest.mark.asyncio` マーカーは**任意**(無くても async テストは収集・実行される)。本プランのテストコード例に付いている `@pytest.mark.asyncio` はそのままでも害は無いが、既存 tests のスタイル(マーカー無し)に合わせて省いてもよい。どちらでも PASS する。`@pytest.mark.qdrant` 等の**機能マーカーは省略不可**(skip 制御に使うため残す)。
- INPUT_INVALID は HTTP 400。テスト規約: ローカル client フィクスチャ = TestClient(create_app()) + monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))、ctx は client.app.state.ctx、サービス差し替えはビルド後に ctx.<service> を上書き。
- npm build 後に apps/web/dist/.gitkeep が消える既知問題があるため、フロントの commit 前に `git checkout -- apps/web/dist/.gitkeep` を行う。
- 埋め込み切替は「再インデックス操作を通じてのみ」有効。embedding_model と collection 次元は一体で動かす。
- **実行順の固定(フロント設定UI の衝突回避)**: `apps/web/src/lib/api/settings.ts` と `apps/web/src/routes/settings/+page.svelte` は Task 3(全体既定LLM `<select>` + `putOllama`)と Task 8(埋め込み `<select>` + 警告 + SSE 進捗)の両方が触る。**必ず Task 3 → Task 8 の順で適用**し、**Task 8 は Task 3 適用後のファイルを `old_string` に取り、全置換でなく部分編集**(追記/該当行のみ差し替え)で行う。Task 8 は Task 3 が入れた `putOllama`(settings.ts / store)・既定LLM `<select>`・`onDefaultModelChange`/`chatModelNames` を**保持**し、埋め込みモデル行のみ差し替える。全置換すると Task 3 の (B-1) 成果が消える。

---

### Task 1: モデル分類 classify_kind と /api/models への kind 付与

**Files:**
- Modify: `core/ollama/models_info.py`
- Modify: `apps/api/routers/models.py` (list_models ループ, 約 L23-42)
- Modify: `apps/web/src/lib/api/types.ts` (ModelInfo, L102-108)
- Test: `tests/unit/test_models_info.py` (既存に追記)

**Interfaces:**
- Consumes: なし(本プラン先頭タスク)。既存のみ利用:
  - `OllamaClient.show(name) -> dict`(`/api/show` の生 json。新しい Ollama は `"capabilities": list[str]` を含む)
  - `core.ollama.models_info.classify_recommendation`, `parse_context_window`(既存・変更なし)
- Produces(後続 Task 2/4/8 が依存):
  - `core.ollama.models_info.classify_kind(*, capabilities: list[str], name: str) -> str`
    - 返り値の値域: `"chat" | "embedding" | "both" | "unknown"`(リテラル文字列)
    - 判定規約: `capabilities` を一次情報とする。`"embedding"` を含めば embedding 側、`"completion"` または `"chat"` を含めば chat 側、両側真→`"both"`、片側のみ→該当文字列。capabilities が空(または両シグナル無し)→名前フォールバック。フォールバックで小文字名に `embed` / `bge` / `nomic-embed` / `mxbai` / `snowflake-arctic-embed` / `all-minilm` のいずれかを含めば `"embedding"`、それ以外は `"chat"`。capabilities が「空 かつ name も空文字」のように両シグナル皆無のときのみ `"unknown"`。
  - `/api/models` レスポンスの各 model dict に `"kind"` キー(上記値域)が付与される。
  - フロント `ModelInfo.kind: "chat" | "embedding" | "both" | "unknown"`。

- [ ] **Step 1: classify_kind の失敗テストを書く(capabilities 優先 / フォールバック / both / unknown)**
  `tests/unit/test_models_info.py` の import 行を `classify_kind` を含む形に変更し、ファイル末尾に以下を追記する。

  まず import 行(1行目)を置換:
  ```python
  from core.ollama.models_info import (
      classify_kind,
      classify_recommendation,
      parse_context_window,
  )
  ```

  ファイル末尾(`test_parse_context_window_missing_returns_none` の後)に追記:
  ```python
  def test_classify_kind_capabilities_embedding_wins_over_name():
      # capabilities が一次情報。名前が chat 風でも capabilities を優先。
      assert (
          classify_kind(capabilities=["embedding"], name="qwen2.5:14b")
          == "embedding"
      )


  def test_classify_kind_capabilities_completion_is_chat():
      assert (
          classify_kind(capabilities=["completion"], name="anything") == "chat"
      )


  def test_classify_kind_capabilities_chat_is_chat():
      assert classify_kind(capabilities=["chat"], name="anything") == "chat"


  def test_classify_kind_capabilities_both():
      assert (
          classify_kind(capabilities=["completion", "embedding"], name="foo")
          == "both"
      )


  def test_classify_kind_fallback_embedding_by_name():
      # capabilities 空 → 名前ヒューリスティック。
      assert classify_kind(capabilities=[], name="bge-m3") == "embedding"
      assert (
          classify_kind(capabilities=[], name="nomic-embed-text") == "embedding"
      )
      assert (
          classify_kind(capabilities=[], name="mxbai-embed-large") == "embedding"
      )
      assert (
          classify_kind(capabilities=[], name="snowflake-arctic-embed:l")
          == "embedding"
      )
      assert classify_kind(capabilities=[], name="all-minilm") == "embedding"


  def test_classify_kind_fallback_chat_by_default():
      assert classify_kind(capabilities=[], name="qwen2.5:14b") == "chat"


  def test_classify_kind_unknown_when_no_signal():
      # capabilities 空 かつ name も空 → 判定不能。
      assert classify_kind(capabilities=[], name="") == "unknown"
  ```

- [ ] **Step 2: 失敗を確認する**
  Run: `uv run pytest tests/unit/test_models_info.py -v`
  Expected: FAIL(`ImportError: cannot import name 'classify_kind' from 'core.ollama.models_info'`)。

- [ ] **Step 3: classify_kind を最小実装する**
  `core/ollama/models_info.py` の `_LONG_CTX_THRESHOLD = 65536` 行の直後(`classify_recommendation` 定義の直前)に、フォールバック用の名前マーカー定数を追加する。
  既存:
  ```python
  _LONG_CTX_THRESHOLD = 65536
  ```
  に置換:
  ```python
  _LONG_CTX_THRESHOLD = 65536
  _EMBED_NAME_MARKERS = (
      "embed",
      "bge",
      "nomic-embed",
      "mxbai",
      "snowflake-arctic-embed",
      "all-minilm",
  )
  ```

  続けて `parse_context_window` 関数の定義の後(ファイル末尾)に `classify_kind` を追記する:
  ```python
  def classify_kind(*, capabilities: list[str], name: str) -> str:
      """Ollama モデルを用途別に分類する。

      返り値: "chat" | "embedding" | "both" | "unknown"。
      一次情報は /api/show の capabilities。空ならば名前ヒューリスティックに
      フォールバックする。
      """
      caps = {c.lower() for c in (capabilities or [])}
      has_embedding = "embedding" in caps
      has_chat = "completion" in caps or "chat" in caps
      if has_embedding and has_chat:
          return "both"
      if has_embedding:
          return "embedding"
      if has_chat:
          return "chat"

      # フォールバック: 名前ヒューリスティック。
      name_lower = (name or "").lower()
      if not name_lower:
          return "unknown"
      if any(marker in name_lower for marker in _EMBED_NAME_MARKERS):
          return "embedding"
      return "chat"
  ```

- [ ] **Step 4: ユニットテストの成功を確認する**
  Run: `uv run pytest tests/unit/test_models_info.py -v`
  Expected: PASS(追加 7 ケース + 既存 5 ケースすべて green)。

- [ ] **Step 5: コミットする(分類ロジック + ユニットテスト)**
  ```
  git add core/ollama/models_info.py tests/unit/test_models_info.py
  git commit -m "feat(models): add classify_kind for chat/embedding model classification"
  ```

- [ ] **Step 6: /api/models に kind を付与する**
  `apps/api/routers/models.py` の import 行(L8)を置換:
  既存:
  ```python
  from core.ollama.models_info import classify_recommendation, parse_context_window
  ```
  置換後:
  ```python
  from core.ollama.models_info import (
      classify_kind,
      classify_recommendation,
      parse_context_window,
  )
  ```

  次に list_models のループ本体(`show = await client.show(name)` から `models.append({...})` まで)を以下に置換する。既存:
  ```python
        show = await client.show(name)
        params_str = show.get("parameters", "")
        ctx_window = parse_context_window(params_str)
        models.append(
            {
                "name": name,
                "size_bytes": tag.get("size"),
                "context_window": ctx_window,
                "modified_at": tag.get("modified_at"),
                "recommended_for": classify_recommendation(
                    name=name,
                    family=details.get("family", ""),
                    parameter_size=details.get("parameter_size", ""),
                    context_window=ctx_window,
                ),
            }
        )
  ```
  置換後:
  ```python
        show = await client.show(name)
        params_str = show.get("parameters", "")
        ctx_window = parse_context_window(params_str)
        capabilities = show.get("capabilities", []) or []
        models.append(
            {
                "name": name,
                "size_bytes": tag.get("size"),
                "context_window": ctx_window,
                "modified_at": tag.get("modified_at"),
                "kind": classify_kind(capabilities=capabilities, name=name),
                "recommended_for": classify_recommendation(
                    name=name,
                    family=details.get("family", ""),
                    parameter_size=details.get("parameter_size", ""),
                    context_window=ctx_window,
                ),
            }
        )
  ```

- [ ] **Step 7: 既存統合テストを壊していないか確認する**
  Run: `uv run pytest tests/integration/test_api/test_models_api.py -v`
  Expected: PASS。`/api/models` を叩く既存 models 統合テストが kind 追加後も全て green のままであること(`kind` キーが増えても既存アサーションは壊れない。レスポンス JSON に新キーが増えるだけで既存キーの値は不変)。新規統合テストは過剰になるため本タスクでは追加しない(kind はユニットで網羅済み)。
  > 注: ファイル名は `tests/integration/test_api/test_models_api.py`(実在を確認済み。本プラン他所でも参照)。`-k models` のような曖昧マッチで `no tests ran` を許容しない(誤誘導になるため、対象ファイルを直指定して PASS を要求する)。

- [ ] **Step 8: フロント ModelInfo に kind を追加する**
  `apps/web/src/lib/api/types.ts` の `ModelInfo`(L102-108)を置換。既存:
  ```typescript
  export interface ModelInfo {
    name: string;
    size_bytes: number | null;
    context_window: number | null;
    modified_at: string;
    recommended_for: string[];
  }
  ```
  置換後:
  ```typescript
  export interface ModelInfo {
    name: string;
    size_bytes: number | null;
    context_window: number | null;
    modified_at: string;
    kind: "chat" | "embedding" | "both" | "unknown";
    recommended_for: string[];
  }
  ```

- [ ] **Step 9: フロントの型チェックを確認する**
  Run: `cd apps/web && npm run check`
  Expected: PASS(`svelte-check` が 0 errors。`ModelInfo` の追加プロパティで既存利用箇所が壊れていないこと。もし既存のモック/フィクスチャで `kind` 欠落エラーが出た場合のみ、その箇所に `kind: "chat"` を補う)。

- [ ] **Step 10: コミットする(API kind 付与 + フロント型)**
  ```
  git add apps/api/routers/models.py apps/web/src/lib/api/types.ts
  git commit -m "feat(models): expose model kind via /api/models and ModelInfo type"
  ```

---

### Task 2: 全体既定LLM: PUT /api/settings/ollama と apply_overrides 拡張

設計仕様 (B-1) のバックエンドを実装する。全体既定チャットモデルを `PUT /api/settings/ollama` で更新し、`settings.json` の `ollama` セクションへ永続化。起動時 `apply_overrides` を `ollama` セクションへ拡張(本タスクでは `default_model` のみ反映)。検証は Ollama の `list_tags()` に存在し、かつ Task 1 の `classify_kind(...)` が `"chat"` か `"both"` であること。違反は HTTP 400(`INPUT_INVALID`)。

**Files:**
- Modify: `apps/api/schemas/settings.py`(`OllamaSettingsUpdate` を追加)
- Modify: `apps/api/routers/settings.py`(`PUT /api/settings/ollama` を追加)
- Modify: `core/settings_store.py:38`(`apply_overrides` に `ollama` マージを追加)
- Test: `tests/integration/test_api/test_settings_ollama_put.py`(新規・統合)
- Test: `tests/integration/test_settings_ollama_overrides.py`(新規・`apply_overrides` 単体寄り統合)

**Interfaces:**
- Consumes(Task 1 が `core/ollama/models_info.py` に Produce 済み):
  - `classify_kind(*, capabilities: list[str], name: str) -> str`(返り値は `"chat" | "embedding" | "both" | "unknown"` のいずれか)
- Consumes(既存・確認済み):
  - `OllamaClient(endpoint: str, timeout: float).list_tags() -> list[dict]`(各 dict は `"name"` キーを持つ)、`.show(model: str) -> dict`(`"capabilities": list[str]` を含み得る生 json)
  - `core.settings_store.save_section(data_dir: Path, section: str, values: dict) -> None`
  - `core.exceptions.AppError(code: ErrorCode, message: str, ...)` / `ErrorCode.INPUT_INVALID`(`main.py` の exception_handler で HTTP 400 にマップ済み)
  - `apps.api.schemas.settings.OllamaSettingsSchema(endpoint: str, default_model: str, embedding_model: str)`
- Produces(後続タスク/フロントが依存する I/O 契約):
  - `OllamaSettingsUpdate(BaseModel)` with field `default_model: str`
  - `PUT /api/settings/ollama` — request body = `OllamaSettingsUpdate`(JSON `{"default_model": "<name>"}`)、success response 200 = `OllamaSettingsSchema`(更新後)、検証失敗 400 = `{"error": {"code": "input.invalid", ...}}`。副作用: in-memory `cfg.ollama.default_model` 更新 + `settings.json` の `ollama` セクションを**マージ書込**(`default_model` のみ更新、`embedding_model`/`embedding_dim` は既存永続値=無ければ cfg 既定を保持)。
  - `apply_overrides` 拡張: `settings.json` の `ollama.default_model` を起動時に `config.ollama.default_model` へ反映(他キーは保持/無視)。

---

- [ ] **Step 1: スキーマ `OllamaSettingsUpdate` の失敗テストを追加する**

  `tests/integration/test_api/test_settings_ollama_put.py` を新規作成し、まずスキーマ存在と基本契約だけを確認する最小テストを書く(この時点では import が失敗して赤になる)。

  `tests/integration/test_api/test_settings_ollama_put.py`:
  ```python
  from __future__ import annotations

  import json

  import httpx
  import pytest
  import respx
  from fastapi.testclient import TestClient

  from apps.api.main import create_app


  @pytest.fixture
  def client(tmp_path, monkeypatch):
      monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
      monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
      app = create_app()
      with TestClient(app) as c:
          yield c


  def _mock_tags_and_show(router, *, name: str, capabilities: list[str]) -> None:
      router.get("http://fake/api/tags").mock(
          return_value=httpx.Response(
              200,
              json={"models": [{"name": name, "size": 1}]},
          )
      )
      router.post("http://fake/api/show").mock(
          return_value=httpx.Response(200, json={"capabilities": capabilities})
      )


  def test_ollama_settings_update_schema_accepts_default_model():
      from apps.api.schemas.settings import OllamaSettingsUpdate

      body = OllamaSettingsUpdate(default_model="qwen2.5:14b")
      assert body.default_model == "qwen2.5:14b"
  ```

- [ ] **Step 2: 失敗を確認する**

  Run: `uv run pytest tests/integration/test_api/test_settings_ollama_put.py -v`
  Expected: FAIL(`ImportError: cannot import name 'OllamaSettingsUpdate' from 'apps.api.schemas.settings'`)。

- [ ] **Step 3: `OllamaSettingsUpdate` を実装する(最小)**

  `apps/api/schemas/settings.py` の `OllamaSettingsSchema` 定義の直後に追記する(既存 `OllamaSettingsSchema` は読取専用のまま変更しない)。

  挿入位置(既存):
  ```python
  class OllamaSettingsSchema(BaseModel):
      endpoint: str
      default_model: str
      embedding_model: str
  ```
  この直後に追加:
  ```python


  class OllamaSettingsUpdate(BaseModel):
      default_model: str
  ```

- [ ] **Step 4: 成功を確認する**

  Run: `uv run pytest tests/integration/test_api/test_settings_ollama_put.py::test_ollama_settings_update_schema_accepts_default_model -v`
  Expected: PASS。

- [ ] **Step 5: コミットする**

  Run:
  ```bash
  git add apps/api/schemas/settings.py tests/integration/test_api/test_settings_ollama_put.py
  git commit -m "feat(settings): add OllamaSettingsUpdate write schema"
  ```
  Expected: 1 file changed (schema) + 1 new test file がコミットされる。

- [ ] **Step 6: PUT エンドポイントの「正常系(chat-capable→200+永続化)」失敗テストを追加する**

  `tests/integration/test_api/test_settings_ollama_put.py` に追記する。`respx` で `/api/tags` と `/api/show` を fake(モデルは chat capability)。

  ```python
  def test_put_ollama_accepts_chat_model_and_persists(client, tmp_path):
      with respx.mock(assert_all_called=False) as router:
          _mock_tags_and_show(router, name="qwen2.5:14b", capabilities=["completion"])
          r = client.put("/api/settings/ollama", json={"default_model": "qwen2.5:14b"})
      assert r.status_code == 200
      assert r.json()["default_model"] == "qwen2.5:14b"

      # 同一プロセス内 GET で反映
      again = client.get("/api/settings").json()["ollama"]
      assert again["default_model"] == "qwen2.5:14b"

      # 永続化ファイル
      sj = tmp_path / "settings.json"
      assert sj.exists()
      saved = json.loads(sj.read_text(encoding="utf-8"))["ollama"]
      assert saved["default_model"] == "qwen2.5:14b"
      # ollama セクションはマージ更新。既存 ollama 永続値が無い初回は
      # in-memory cfg(既定)から embedding_model/embedding_dim を補完する。
      assert saved["embedding_model"] == "bge-m3"
      assert saved["embedding_dim"] == 1024
  ```

  注: この `embedding_dim == 1024` は「既存 ollama 永続値が無い初回 PUT では in-memory cfg の既定(`OllamaSettings.embedding_dim=1024`、Task 5 Step 13 で追加)へフォールバックする」結果である。固定値 1024 をハードコード書込しているのではない。既存の非既定 dim が温存されることは Step 11b の保持テストで担保する。

- [ ] **Step 7: 失敗を確認する**

  Run: `uv run pytest tests/integration/test_api/test_settings_ollama_put.py::test_put_ollama_accepts_chat_model_and_persists -v`
  Expected: FAIL(404 Not Found。`PUT /api/settings/ollama` 未実装のため)。

- [ ] **Step 8: PUT エンドポイントを実装する**

  `apps/api/routers/settings.py` を編集する。import を追加し、`put_audio_settings` の直後に新エンドポイントを追加する。

  まず import 行を変更する。既存:
  ```python
  from apps.api.schemas.settings import (
      AppSettingsSchema,
      AudioSettingsSchema,
      GenerationSettingsSchema,
      OllamaSettingsSchema,
      RetrievalSettingsSchema,
  )
  ```
  を次に置き換える(`OllamaSettingsUpdate` を追加):
  ```python
  from apps.api.schemas.settings import (
      AppSettingsSchema,
      AudioSettingsSchema,
      GenerationSettingsSchema,
      OllamaSettingsSchema,
      OllamaSettingsUpdate,
      RetrievalSettingsSchema,
  )
  from core.exceptions import AppError, ErrorCode
  from core.ollama.client import OllamaClient
  from core.ollama.models_info import classify_kind
  ```

  次に、`put_audio_settings` 関数(`return body` で終わる)の直後に以下を追加する:
  ```python


  @router.put("/settings/ollama", response_model=OllamaSettingsSchema)
  async def put_ollama_settings(
      request: Request, body: OllamaSettingsUpdate
  ) -> OllamaSettingsSchema:
      cfg = request.app.state.ctx.config
      client = OllamaClient(
          endpoint=cfg.ollama.endpoint,
          timeout=cfg.ollama.request_timeout_seconds,
      )
      tags = await client.list_tags()
      names = {t.get("name") for t in tags}
      if body.default_model not in names:
          raise AppError(
              ErrorCode.INPUT_INVALID,
              f"model {body.default_model} not found in Ollama",
              remediation="ollama pull で取得済みのモデル名を指定してください。",
          )
      show = await client.show(body.default_model)
      kind = classify_kind(
          capabilities=show.get("capabilities", []) or [],
          name=body.default_model,
      )
      if kind not in ("chat", "both"):
          raise AppError(
              ErrorCode.INPUT_INVALID,
              f"model {body.default_model} is not a chat model (kind={kind})",
              remediation="チャット可能なモデル(chat / both)を選択してください。",
          )

      # in-memory 反映
      cfg.ollama = cfg.ollama.model_copy(update={"default_model": body.default_model})

      # 永続化: ollama セクションをマージ更新する(audio 方式と整合)。
      # default_model のみ更新し、既存の embedding_model / embedding_dim は
      # 「現在の永続値 > in-memory cfg」の優先で保持する。これにより、Task 7 で
      # 768 等へ切替後にユーザが LLM 既定を変えても embedding_dim が 1024 へ
      # 巻き戻らない(決定事項「model と次元は一体」を破壊しない)。
      from core.settings_store import load_overrides, save_section

      existing = load_overrides(cfg.data_dir).get("ollama")
      existing = existing if isinstance(existing, dict) else {}
      embedding_model = existing.get("embedding_model", cfg.ollama.embedding_model)
      # getattr で Task5(OllamaSettings.embedding_dim 追加)の前後どちらでも動く。
      # 既存永続値 > in-memory cfg.embedding_dim(Task5 後) > 既定 1024(Task5 前)。
      embedding_dim = existing.get(
          "embedding_dim", getattr(cfg.ollama, "embedding_dim", 1024)
      )
      save_section(
          cfg.data_dir,
          "ollama",
          {
              "default_model": cfg.ollama.default_model,
              "embedding_model": embedding_model,
              "embedding_dim": embedding_dim,
          },
      )
      return OllamaSettingsSchema(
          endpoint=cfg.ollama.endpoint,
          default_model=cfg.ollama.default_model,
          embedding_model=cfg.ollama.embedding_model,
      )
  ```

  注(順序非依存): `embedding_dim` の解決は `getattr(cfg.ollama, "embedding_dim", 1024)` を使うため、**Task 5(`OllamaSettings.embedding_dim` 追加)の前後どちらでも動く**(Task 5 前は既定 1024 へ、後は cfg 値へフォールバック)。優先順位は「① 既存永続値 `existing.get("embedding_dim")` → ② in-memory `cfg.ollama.embedding_dim`(Task5 後) → ③ 既定 1024(Task5 前)」。本タスクは `VectorStore.collection_dim()` 等の Task 5/7 で追加される実 API は**参照しない**(参照すると Task 2 単体で AttributeError)。埋め込み次元の確定書込(現行 collection dim での更新)は Task 7 の再インデックスの責務。本 PUT は「既存の埋め込み次元を保持して壊さない(1024 へ巻き戻さない)」ことだけを責務とする。なお `collection_dim()` を使う「より正確な dim 反映」は Task 5 完了後に Step 8 の `embedding_dim` 行を `ctx.vector_store.collection_dim() or <上記フォールバック>` へ差し替えてもよい(任意・後続改善)。

- [ ] **Step 9: 成功を確認する**

  Run: `uv run pytest tests/integration/test_api/test_settings_ollama_put.py::test_put_ollama_accepts_chat_model_and_persists -v`
  Expected: PASS。

- [ ] **Step 10: 異常系(embedding-only→400 / 存在しないモデル→400)の失敗テストを追加する**

  `tests/integration/test_api/test_settings_ollama_put.py` に追記する。

  ```python
  def test_put_ollama_rejects_embedding_only_model(client):
      with respx.mock(assert_all_called=False) as router:
          _mock_tags_and_show(router, name="bge-m3", capabilities=["embedding"])
          r = client.put("/api/settings/ollama", json={"default_model": "bge-m3"})
      assert r.status_code == 400
      assert r.json()["error"]["code"] == "input.invalid"


  def test_put_ollama_rejects_unknown_model(client):
      with respx.mock(assert_all_called=False) as router:
          # tags には別モデルしか無い → 指定モデルは未存在
          router.get("http://fake/api/tags").mock(
              return_value=httpx.Response(
                  200, json={"models": [{"name": "qwen2.5:14b", "size": 1}]}
              )
          )
          r = client.put("/api/settings/ollama", json={"default_model": "does-not-exist"})
      assert r.status_code == 400
      assert r.json()["error"]["code"] == "input.invalid"
  ```

- [ ] **Step 11: 成功を確認する(エンドポイント全テスト)**

  Run: `uv run pytest tests/integration/test_api/test_settings_ollama_put.py -v`
  Expected: 4 件すべて PASS(schema / chat→200+persist / embedding→400 / unknown→400)。

- [ ] **Step 11b: 既存 embedding_dim を巻き戻さない保持テストを追加する(根本原因E の回帰防止)**

  事前に settings.json の `ollama` セクションへ非既定の埋め込み次元(768 / nomic-embed-text)を書いておき、`PUT /api/settings/ollama` で LLM 既定を変えても `embedding_model` / `embedding_dim` が温存されることを確認する。これは「Task 7 で 768 へ切替後、LLM 既定変更で 1024 へ巻き戻る」破綻(根本原因E)を構造的に防ぐ回帰テスト。`tests/integration/test_api/test_settings_ollama_put.py` に追記する。

  ```python
  def test_put_ollama_preserves_existing_embedding_dim(tmp_path, monkeypatch):
      monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
      monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
      # 先に非既定の埋め込みを永続化(再インデックス済み状態を模す)
      (tmp_path / "settings.json").write_text(
          json.dumps(
              {
                  "ollama": {
                      "default_model": "qwen2.5:14b",
                      "embedding_model": "nomic-embed-text",
                      "embedding_dim": 768,
                  }
              }
          ),
          encoding="utf-8",
      )
      with TestClient(create_app()) as c:
          with respx.mock(assert_all_called=False) as router:
              _mock_tags_and_show(
                  router, name="llama3.1:8b", capabilities=["completion"]
              )
              r = c.put("/api/settings/ollama", json={"default_model": "llama3.1:8b"})
          assert r.status_code == 200

      saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["ollama"]
      # LLM 既定は更新される
      assert saved["default_model"] == "llama3.1:8b"
      # 埋め込みは巻き戻らず温存される(1024 に戻らない)
      assert saved["embedding_model"] == "nomic-embed-text"
      assert saved["embedding_dim"] == 768
  ```

  Run: `uv run pytest tests/integration/test_api/test_settings_ollama_put.py::test_put_ollama_preserves_existing_embedding_dim -v`
  Expected: PASS(マージ保持により 768/nomic-embed-text が温存される。固定 1024 書込の旧実装では FAIL する回帰)。

- [ ] **Step 12: コミットする**

  Run:
  ```bash
  git add apps/api/routers/settings.py tests/integration/test_api/test_settings_ollama_put.py
  git commit -m "feat(settings): add PUT /api/settings/ollama with chat-kind validation"
  ```
  Expected: router + テスト追記分がコミットされる。

- [ ] **Step 13: `apply_overrides` の `ollama` 適用テスト(失敗)を追加する**

  `tests/integration/test_settings_ollama_overrides.py` を新規作成する。`settings.json` に `ollama.default_model` を手で書き、新 app 起動後 `GET /api/settings` で反映されることを確認する。

  `tests/integration/test_settings_ollama_overrides.py`:
  ```python
  from __future__ import annotations

  import json

  from fastapi.testclient import TestClient

  from apps.api.main import create_app


  def test_apply_overrides_applies_ollama_default_model(memory_data_dir):
      (memory_data_dir / "settings.json").write_text(
          json.dumps(
              {
                  "ollama": {
                      "default_model": "llama3.1:8b",
                      "embedding_model": "bge-m3",
                      "embedding_dim": 1024,
                  }
              }
          ),
          encoding="utf-8",
      )
      with TestClient(create_app()) as client:
          ollama = client.get("/api/settings").json()["ollama"]
          assert ollama["default_model"] == "llama3.1:8b"
          # embedding_model は保持される(本タスクでは default_model のみ反映対象)。
          assert ollama["embedding_model"] == "bge-m3"


  def test_invalid_ollama_override_does_not_crash_startup(memory_data_dir):
      """型不正な ollama オーバーライドで起動をクラッシュさせず既定で続行する。"""
      (memory_data_dir / "settings.json").write_text(
          '{"ollama": {"default_model": 12345}}', encoding="utf-8"
      )
      with TestClient(create_app()) as client:
          r = client.get("/api/settings")
          assert r.status_code == 200
          # 既定モデルに戻る(core/config.py OllamaSettings.default_model)。
          assert r.json()["ollama"]["default_model"] == "qwen2.5:14b"
  ```

  `memory_data_dir` フィクスチャは `tests/conftest.py` で定義済み(`monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))`)なので import 不要。

- [ ] **Step 14: 失敗を確認する**

  Run: `uv run pytest tests/integration/test_settings_ollama_overrides.py -v`
  Expected: `test_apply_overrides_applies_ollama_default_model` が FAIL(`apply_overrides` が `ollama` を見ないため `default_model` が既定 `qwen2.5:14b` のまま)。`test_invalid_...` は既定で続行するため偶然 PASS する可能性がある。

- [ ] **Step 15: `apply_overrides` を `ollama` 対応に拡張する**

  `core/settings_store.py` の `apply_overrides` 末尾(`audio` ブロックの直後)に `ollama` ブロックを追加する。`audio` と同じ try/except パターン。本タスクでは `default_model` のみマージ反映し、他キー(`embedding_model`/`embedding_dim`)は現行値を保持する(= マージしない)。

  既存 `apply_overrides` の末尾:
  ```python
      ov = load_overrides(config.data_dir)
      audio = ov.get("audio")
      if isinstance(audio, dict) and audio:
          merged = {**config.audio.model_dump(), **audio}
          try:
              config.audio = config.audio.__class__(**merged)
          except Exception:
              # 不正な settings.json で起動をクラッシュさせない (既定値で続行)。
              log.warning("settings_override_invalid", section="audio")
  ```
  を次に置き換える(`ollama` ブロックを追加):
  ```python
      ov = load_overrides(config.data_dir)
      audio = ov.get("audio")
      if isinstance(audio, dict) and audio:
          merged = {**config.audio.model_dump(), **audio}
          try:
              config.audio = config.audio.__class__(**merged)
          except Exception:
              # 不正な settings.json で起動をクラッシュさせない (既定値で続行)。
              log.warning("settings_override_invalid", section="audio")

      ollama = ov.get("ollama")
      if isinstance(ollama, dict) and ollama:
          # 本タスクでは default_model のみ適用する。embedding_model/embedding_dim の
          # 起動時適用は dim 動的化(後続タスク)と整合させるため、ここでは保持/無視する。
          default_model = ollama.get("default_model")
          if default_model is not None:
              merged = {
                  **config.ollama.model_dump(),
                  "default_model": default_model,
              }
              try:
                  config.ollama = config.ollama.__class__(**merged)
              except Exception:
                  # 不正な settings.json で起動をクラッシュさせない (既定値で続行)。
                  log.warning("settings_override_invalid", section="ollama")
  ```

- [ ] **Step 16: 成功を確認する**

  Run: `uv run pytest tests/integration/test_settings_ollama_overrides.py -v`
  Expected: 2 件とも PASS。

- [ ] **Step 17: 永続化→再起動の一貫性を確認する(回帰)**

  PUT で保存した値が `apply_overrides` 経由で新 app 起動時にも反映されることを示す回帰テストを `tests/integration/test_api/test_settings_ollama_put.py` に追記する。これにより Step 8(書込)と Step 15(読込)の結線を担保する。

  ```python
  def test_put_ollama_persists_across_restart(tmp_path, monkeypatch):
      monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
      monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
      with TestClient(create_app()) as c1:
          with respx.mock(assert_all_called=False) as router:
              _mock_tags_and_show(router, name="qwen2.5:14b", capabilities=["completion"])
              r = c1.put("/api/settings/ollama", json={"default_model": "qwen2.5:14b"})
          assert r.status_code == 200

      # 新 app(同 data_dir)起動 → apply_overrides で反映
      with TestClient(create_app()) as c2:
          ollama = c2.get("/api/settings").json()["ollama"]
          assert ollama["default_model"] == "qwen2.5:14b"
  ```

- [ ] **Step 18: 成功を確認する(本タスク全テスト)**

  Run: `uv run pytest tests/integration/test_api/test_settings_ollama_put.py tests/integration/test_settings_ollama_overrides.py -v`
  Expected: すべて PASS(PUT 6 件: schema / chat→200+persist / embedding→400 / unknown→400 / 既存 dim 保持 / 再起動回帰 + overrides 2 件)。

- [ ] **Step 19: 既存テスト非破壊を確認する**

  Run: `uv run pytest tests/integration/test_settings_audio.py tests/integration/test_api/test_settings_api.py -v`
  Expected: すべて PASS(`apply_overrides` の audio 経路・既存 settings 経路を壊していないこと)。

- [ ] **Step 20: コミットする**

  Run:
  ```bash
  git add core/settings_store.py tests/integration/test_settings_ollama_overrides.py tests/integration/test_api/test_settings_ollama_put.py
  git commit -m "feat(settings): apply ollama.default_model override on startup"
  ```
  Expected: `apply_overrides` 拡張 + overrides テスト + 再起動回帰テストがコミットされる。

---

補足(後続タスク向けメモ):
- 本タスクの PUT は `ollama` セクションをマージ更新し、`embedding_model`/`embedding_dim` は既存永続値(無ければ in-memory cfg 既定)を**保持**する(固定 1024 を上書き書込しない)。これにより根本原因E(LLM 既定変更で埋め込み次元が 1024 へ巻き戻る)を構造的に防ぐ。
- 順序依存: `cfg.ollama.embedding_dim` の参照は Task 5 Step 13(`OllamaSettings.embedding_dim` 追加)完了後に成立する。実装順は Task 2 本体 → Task 5 → 本フォールバックが有効。
- 埋め込み次元の「確定書込(現行 collection dim での更新)」は Task 7 の再インデックス時の責務。本 PUT は次元を**変えない/壊さない**ことだけを担う。
- `apply_overrides` は意図的に `embedding_model`/`embedding_dim` を起動時適用しない(再インデックスフロー = 設計 (C) でのみ反映)。この方針を崩さないこと。
- `OllamaClient` をルータ内で直接 new する設計は既存 `apps/api/routers/models.py` と一致。gateway(`ctx.ollama`)は `list_tags`/`show` を持たないため使わない。テストの fake は `respx` + `NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT=http://fake` で行う(`test_models_api.py` と同方式)。

---

### Task 3: 設定UI — 全体既定LLM セレクト (`<select>` + `putOllama`)

**Files:**
- Modify: `apps/web/src/lib/api/types.ts` (`ModelInfo` 拡張は Task 1 が実施済み前提。本タスクで `OllamaSettingsUpdate` 型を追加)
- Modify: `apps/web/src/lib/api/settings.ts` (`putOllama` 追加)
- Modify: `apps/web/src/lib/stores/settings.svelte.ts` (`putOllama` ラッパ追加)
- Modify: `apps/web/src/routes/settings/+page.svelte` (`section==='models'` の「既定モデル」`<dd>` を `<select>` 化)
- Test: フロントは型/ビルド健全性 (`npm run check`) を健全性ゲートとする。視覚は最終 Playwright ゲート(末尾ステップ参照)。

**Interfaces:**

Consumes:
- Task 1: `ModelInfo.kind: "chat" | "embedding" | "both" | "unknown"`(`apps/web/src/lib/api/types.ts` の `ModelInfo` に追加済みであること)。
- Task 2: `PUT /api/settings/ollama`(リクエスト body `{ "default_model": string }`、レスポンス body は更新後の `OllamaSettings`(`{ endpoint, default_model, embedding_model }`)。chat/both 以外は HTTP 400 / `INPUT_INVALID`)。
- 既存: `request<T>(path, options)`(`apps/web/src/lib/api/client.ts`)。`ApiError`(`.message` を持つ)。
- 既存: `pushToast(message: string, level?: 'info'|'success'|'error', duration?: number)`(`apps/web/src/lib/components/Toast.svelte` の module export)。
- 既存: `settingsStore.settings.ollama.default_model`、`settingsStore.load()`(`apps/web/src/lib/stores/settings.svelte.ts`)。
- 既存: `modelsStore.models: ModelInfo[]`(`apps/web/src/lib/stores/models.svelte.ts`)。

Produces:
- `settingsApi.putOllama(body: { default_model: string }): Promise<OllamaSettings>`(`apps/web/src/lib/api/settings.ts`)。
- `settingsStore.putOllama(default_model: string): Promise<void>`(成功時 in-place で `settings.ollama.default_model` を楽観更新したうえで `load()` 再取得、失敗時は例外を再 throw して呼び出し側がロールバック)。
- `OllamaSettingsUpdate` 型(`apps/web/src/lib/api/types.ts`)。

---

- [ ] **Step 1: `OllamaSettingsUpdate` 型を types.ts に追加**

  `apps/web/src/lib/api/types.ts` の既存 `OllamaSettings` インターフェース定義(`endpoint`/`default_model`/`embedding_model` を持つブロック)の直後に、以下を追加する。

```ts
export interface OllamaSettingsUpdate {
  default_model: string;
}
```

  - 注: `ModelInfo.kind` は Task 1 が同ファイルに追加済みの前提。本タスクでは `ModelInfo` を編集しない。もし `ModelInfo` に `kind` が無ければ Task 1 が未完了なので、ここで停止し先行タスクの完了を確認すること。

- [ ] **Step 2: 型確認(コンパイル健全性)**

  Run: `cd apps/web && npm run check`
  Expected: 既存の型エラーが無いこと(`ModelInfo.kind` が存在し、`OllamaSettingsUpdate` 追加で新規エラーが出ないこと)。`kind` 未定義のエラーが出る場合は Task 1 未完了。

- [ ] **Step 3: `settingsApi.putOllama` を settings.ts に追加**

  `apps/web/src/lib/api/settings.ts` を以下の内容で置き換える(import に `OllamaSettings`/`OllamaSettingsUpdate` を追加し、`putOllama` を追加)。

```ts
import { request } from './client';
import type {
  AppSettings,
  AudioSettings,
  OllamaSettings,
  OllamaSettingsUpdate,
  Stats,
} from './types';

export const settingsApi = {
  get: () => request<AppSettings>('/api/settings'),
  stats: () => request<Stats>('/api/stats'),
  putAudio: (audio: AudioSettings) =>
    request<AudioSettings>('/api/settings/audio', {
      method: 'PUT',
      body: JSON.stringify(audio),
    }),
  putOllama: (body: OllamaSettingsUpdate) =>
    request<OllamaSettings>('/api/settings/ollama', {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
};
```

- [ ] **Step 4: 型確認**

  Run: `cd apps/web && npm run check`
  Expected: 新規型エラー無し(PASS)。

- [ ] **Step 5: `settingsStore.putOllama` ラッパを追加**

  `apps/web/src/lib/stores/settings.svelte.ts` を編集する。まず `SettingsStore` インターフェースに `putOllama` を追加する。`load(): Promise<void>;` の直後の行に追加する。

```ts
  load(): Promise<void>;
  putOllama(default_model: string): Promise<void>;
```

  次に、`createSettingsStore` の return オブジェクト内、`async load() { ... },` の閉じ `},` の直後に以下のメソッドを追加する。

```ts
    async putOllama(default_model: string) {
      const updated = await api.putOllama({ default_model });
      if (settings) {
        settings = { ...settings, ollama: updated };
      } else {
        await this.load();
      }
    },
```

  - 注: 失敗時(`api.putOllama` が throw)はこのメソッドも throw し、`settings` は変更しない。ロールバックは呼び出し側(+page.svelte の `<select>`)が担う。`settings.svelte.ts` の冒頭 import に型追加は不要(`OllamaSettings` は `api.putOllama` の戻り型で吸収される)。

- [ ] **Step 6: 型確認**

  Run: `cd apps/web && npm run check`
  Expected: PASS(新規型エラー無し)。

- [ ] **Step 7: `section==='models'` の「既定モデル」を `<select>` に変更**

  `apps/web/src/routes/settings/+page.svelte` の `<script>` 末尾(`function goBack() { ... }` の閉じ `}` の直後)に、`<select>` の onchange ハンドラを追加する。

```ts
  function chatModelNames(): string[] {
    return modelsStore.models
      .filter((m) => m.kind === 'chat' || m.kind === 'both')
      .map((m) => m.name);
  }

  async function onDefaultModelChange(e: Event) {
    const select = e.currentTarget as HTMLSelectElement;
    const next = select.value;
    const prev = settingsStore.settings?.ollama.default_model ?? '';
    if (next === prev) return;
    try {
      await settingsStore.putOllama(next);
      pushToast(`既定モデルを ${next} に変更しました`, 'success');
    } catch (err) {
      select.value = prev; // 失敗時は選択を元に戻す
      const msg = err instanceof Error ? err.message : String(err);
      pushToast(`既定モデルの変更に失敗しました: ${msg}`, 'error');
    }
  }
```

  続けて、`<script>` 冒頭の import 群に `pushToast` を追加する(`AudioSettingsSection` の import 行の直後)。

```ts
  import { pushToast } from '$lib/components/Toast.svelte';
```

- [ ] **Step 8: テンプレートの `<dd>` を `<select>` に置換**

  同ファイルの `section === 'models'` ブロック内、以下の2行(既定モデルの `<dt>`/`<dd>`)を置換する。

  置換前:
```svelte
            <dt>既定モデル</dt>
            <dd><code>{settingsStore.settings.ollama.default_model}</code></dd>
```

  置換後:
```svelte
            <dt>既定モデル</dt>
            <dd>
              <select
                class="model-select"
                value={settingsStore.settings.ollama.default_model}
                onchange={onDefaultModelChange}
              >
                {#each chatModelNames() as name (name)}
                  <option value={name}>{name}</option>
                {/each}
                {#if !chatModelNames().includes(settingsStore.settings.ollama.default_model)}
                  <option value={settingsStore.settings.ollama.default_model}>
                    {settingsStore.settings.ollama.default_model}(未検出)
                  </option>
                {/if}
              </select>
            </dd>
```

  - 注: 現在値が一覧(chat/both)に無い場合でも空セレクトにならないよう「(未検出)」option を末尾に補う。これにより `<select>` の現在値表示が常に正しくなる。

- [ ] **Step 9: `.model-select` のスタイルを追加**

  同ファイルの `<style>` 内、`dd { ... }` ルールの直後に以下を追加する。

```css
  .model-select {
    font-size: 13px;
    padding: 4px 8px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-bg);
    color: var(--color-fg);
    min-width: 240px;
    font-family: var(--font-mono);
  }
```

- [ ] **Step 10: 型/ビルド健全性確認**

  Run: `cd apps/web && npm run check`
  Expected: PASS(型エラー無し)。`onDefaultModelChange`・`chatModelNames`・`pushToast`・`OllamaSettingsUpdate` がすべて解決すること。

- [ ] **Step 11: 本番ビルド健全性確認**

  Run: `cd apps/web && npm run build`
  Expected: ビルド成功(`apps/web/dist/` 出力)。

- [ ] **Step 12: dist/.gitkeep を復元(既知問題対策)**

  `npm run build` で `apps/web/dist/.gitkeep` が消える既知問題があるため、commit 前に復元する。

  Run: `git checkout -- apps/web/dist/.gitkeep`
  Expected: 出力なし(復元成功)。`git status -- apps/web/dist/.gitkeep` で削除扱いになっていないこと。

- [ ] **Step 13: commit**

  Run:
  ```
  git add apps/web/src/lib/api/types.ts apps/web/src/lib/api/settings.ts apps/web/src/lib/stores/settings.svelte.ts apps/web/src/routes/settings/+page.svelte
  git commit -m "feat(web): 設定の既定LLMを<select>化しPUT /settings/ollamaで保存"
  ```
  Expected: 1 commit 作成。

- [ ] **Step 14: 視覚検証ゲート(Playwright 実機スクショ必須)**

  本ステップは GUI 変更のため、自動 `npm run check`/`build` の GREEN だけでは PASS にしない(visual regression は検出できない)。実機で以下を確認する。

  1. バックエンド起動: `uv run --extra recording uvicorn apps.api.main:app --port 8765`
  2. フロント dev 起動: `cd apps/web && npm run dev`(API を :8765 へプロキシ)
  3. Playwright MCP でブラウザを `http://localhost:5173/settings` に navigate し、左ナビ「モデル・Ollama」をクリック。
  4. `browser_snapshot` + `browser_take_screenshot` で「既定モデル」が `<select>` として描画され、現在値が選択表示されていること、option に chat/both モデルのみが並ぶことを確認。
  5. `browser_select_option` で別の chat モデルを選択 → 成功トースト「既定モデルを … に変更しました」が出ること、リロード後も選択が保持されること(`settings.json` の `ollama.default_model` 更新を反映)を確認。
  6. (異常系)Ollama に存在しない/埋め込み専用モデルを直接 PUT した場合に 400 となり、UI 側で選択が元に戻りエラートーストが出る経路を確認(embedding-only モデルが一覧にある場合のみ。一覧は chat/both のみなので、この経路は Task 2 の統合テストで担保済みであることを前提に視覚は best-effort)。
  7. スクショを評価レポートに添付。NG 時は self-fix(最大3回)。

  Expected: 既定モデル `<select>` が正しく描画・切替・永続化され、スクショで確認できること(PASS)。

---

関連ファイル(すべて絶対パス):
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\api\types.ts`
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\api\settings.ts`
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\stores\settings.svelte.ts`
- `E:\00_Git\10_NotebookOllama\apps\web\src\routes\settings\+page.svelte`
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\Toast.svelte`(`pushToast` の出所、変更なし)

---

### Task 4: ノート detail のモデルピッカー(ノートごと既定)

**Files:**
- Modify: `apps/web/src/routes/notebooks/[id]/+page.svelte`
- Modify: `apps/web/src/lib/api/types.ts:28` (`NotebookUpdate.default_model` を `null` 許容へ)
- Modify: `apps/web/src/lib/stores/currentNotebook.svelte.ts` (`update` メソッド追加)
- Modify: `apps/api/schemas/notebook.py:12` (`NotebookUpdate` に「null を明示送信＝クリア」を区別させるためのフラグ)
- Modify: `apps/api/routers/notebooks.py:54` (`exclude_unset` でフィールド存在を判定)
- Modify: `core/storage/notebooks_repo.py:72` (`update_notebook` に `clear_default_model` を追加し null クリアを可能に)
- Test: `tests/integration/test_api/test_notebooks_api.py` (null クリアの統合テスト追記)
- Test(視覚): 末尾 Playwright ゲート(後述、スクショ必須)

**Interfaces:**
- Consumes(先行タスク Task 1):
  - `ModelInfo.kind: "chat" | "embedding" | "both" | "unknown"`(`apps/web/src/lib/api/types.ts` の `ModelInfo` に Task 1 が追加済みであること)。
- Consumes(既存・確認済み):
  - `modelsStore.models: ModelInfo[]` / `modelsStore.load(): Promise<void>`(`$lib/stores/models.svelte`)。
  - `settingsStore.settings: AppSettings | null` / `settingsStore.load(): Promise<void>`。`settings.ollama.default_model: string`(`$lib/stores/settings.svelte`)。
  - `currentNotebookStore.notebook: Notebook | null`(`Notebook.default_model: string | null`)。
  - `notebooksApi.update(id: string, body: NotebookUpdate): Promise<Notebook>`(`$lib/api/notebooks`)。
  - `pushToast(message: string, level?: 'info'|'success'|'error'): void`(`$lib/components/Toast.svelte`)。
- Produces(後続が依存):
  - `currentNotebookStore.update(patch: { default_model?: string | null }): Promise<void>` — PATCH を投げ、成功時 `notebook.default_model` を反映。後続タスクが同 store からノート既定を書き換える際に再利用可能。
  - バックエンド: `PATCH /api/notebooks/{id}` が `{"default_model": null}` を**明示クリア**として扱い、レスポンスの `default_model` が `null` になる(従来は無視されていた挙動の修正)。

> 重要な事前発見(推測ではなくコード根拠あり): 現行 `core/storage/notebooks_repo.py:83` は `new_model = default_model if default_model is not None else existing.default_model` のため、`default_model=null` を送っても**既存値が温存され null に戻せない**。設計仕様 (B-2) の「先頭 option で `default_model=null` を送り全体既定に戻す」を成立させるには、この 1 点のバックエンド修正が必須。スコープ注記「バックエンド変更なし」は誤り(既存 PATCH のままでは「既定に戻す」が動かない)。本タスクで最小修正を含める。

- [ ] **Step 1: 失敗する統合テスト(null クリア)を追記**
  `tests/integration/test_api/test_notebooks_api.py` の末尾に以下を追記する。
  ```python
  def test_patch_clears_default_model_with_explicit_null(client):
      # まずモデルを設定
      r = client.post("/api/notebooks", json={"name": "N", "default_model": "qwen2.5:14b"})
      assert r.status_code == 201
      nb_id = r.json()["id"]
      assert r.json()["default_model"] == "qwen2.5:14b"

      # 明示 null でクリア(=全体既定に戻す)
      r = client.patch(f"/api/notebooks/{nb_id}", json={"default_model": None})
      assert r.status_code == 200
      assert r.json()["default_model"] is None

      # フィールド未指定では default_model を変えない(温存)
      r = client.patch(f"/api/notebooks/{nb_id}", json={"default_model": "llama3.1:8b"})
      assert r.status_code == 200
      r = client.patch(f"/api/notebooks/{nb_id}", json={"name": "N2"})
      assert r.status_code == 200
      assert r.json()["name"] == "N2"
      assert r.json()["default_model"] == "llama3.1:8b"
  ```

- [ ] **Step 2: 失敗を確認**
  Run: `uv run pytest tests/integration/test_api/test_notebooks_api.py::test_patch_clears_default_model_with_explicit_null -v`
  Expected: FAIL(`assert r.json()["default_model"] is None` で失敗。理由: 現状 `None` 送信は「変更なし」扱いになり `"qwen2.5:14b"` が残る)。

- [ ] **Step 3: 最小実装(1)repo に null クリア経路を追加**
  `core/storage/notebooks_repo.py` の `update_notebook` を、`default_model` のクリアを明示できるよう変更する。`old_string`:
  ```python
  def update_notebook(
      conn: sqlite3.Connection,
      notebook_id: str,
      *,
      name: str | None = None,
      description: str | None = None,
      default_model: str | None = None,
  ) -> NotebookRecord:
      existing = get_notebook(conn, notebook_id)
      new_name = name if name is not None else existing.name
      new_desc = description if description is not None else existing.description
      new_model = default_model if default_model is not None else existing.default_model
      now = _now()
  ```
  `new_string`:
  ```python
  def update_notebook(
      conn: sqlite3.Connection,
      notebook_id: str,
      *,
      name: str | None = None,
      description: str | None = None,
      default_model: str | None = None,
      clear_default_model: bool = False,
  ) -> NotebookRecord:
      existing = get_notebook(conn, notebook_id)
      new_name = name if name is not None else existing.name
      new_desc = description if description is not None else existing.description
      if clear_default_model:
          new_model = None
      else:
          new_model = default_model if default_model is not None else existing.default_model
      now = _now()
  ```

- [ ] **Step 4: 最小実装(2)router でフィールド存在を判定して clear を渡す**
  `apps/api/routers/notebooks.py` の `update` ハンドラを、Pydantic の `exclude_unset` で「`default_model` が明示送信され、かつ値が `None`」を検出してクリアするよう変更する。`old_string`:
  ```python
  @router.patch("/{notebook_id}", response_model=Notebook)
  async def update(request: Request, notebook_id: str, body: NotebookUpdate) -> Notebook:
      ctx = request.app.state.ctx
      rec = notebooks_repo.update_notebook(
          ctx.conn,
          notebook_id,
          name=body.name,
          description=body.description,
          default_model=body.default_model,
      )
      return _to_schema(rec)
  ```
  `new_string`:
  ```python
  @router.patch("/{notebook_id}", response_model=Notebook)
  async def update(request: Request, notebook_id: str, body: NotebookUpdate) -> Notebook:
      ctx = request.app.state.ctx
      fields = body.model_dump(exclude_unset=True)
      clear_default_model = "default_model" in fields and fields["default_model"] is None
      rec = notebooks_repo.update_notebook(
          ctx.conn,
          notebook_id,
          name=body.name,
          description=body.description,
          default_model=body.default_model,
          clear_default_model=clear_default_model,
      )
      return _to_schema(rec)
  ```

- [ ] **Step 5: 成功を確認 + 既存テスト非破壊**
  Run: `uv run pytest tests/integration/test_api/test_notebooks_api.py tests/integration/test_storage.py -v`
  Expected: PASS(新規 `test_patch_clears_default_model_with_explicit_null` を含め全 GREEN。`test_update_notebook_default_model` も従来通り PASS)。

- [ ] **Step 6: commit(バックエンド)**
  Run:
  ```
  git add core/storage/notebooks_repo.py apps/api/routers/notebooks.py tests/integration/test_api/test_notebooks_api.py
  git commit -m "fix(notebooks): allow PATCH to clear default_model via explicit null"
  ```

- [ ] **Step 7: フロント型を null 許容に修正**
  `apps/web/src/lib/api/types.ts` の `NotebookUpdate` を変更し、`default_model` に `null` を許可する。`old_string`:
  ```typescript
  export interface NotebookUpdate {
    name?: string;
    description?: string;
    default_model?: string;
  }
  ```
  `new_string`:
  ```typescript
  export interface NotebookUpdate {
    name?: string;
    description?: string;
    /** null を明示送信するとノート既定をクリアし全体既定にフォールバックする。 */
    default_model?: string | null;
  }
  ```

- [ ] **Step 8: store に update メソッドを追加(インターフェース宣言)**
  `apps/web/src/lib/stores/currentNotebook.svelte.ts` の `CurrentNotebookStore` インターフェースに `update` を追加する。`old_string`:
  ```typescript
    load(id: string): Promise<void>;
    clear(): void;
    upsertSource(s: Source): void;
  ```
  `new_string`:
  ```typescript
    load(id: string): Promise<void>;
    update(patch: { default_model?: string | null }): Promise<void>;
    clear(): void;
    upsertSource(s: Source): void;
  ```

- [ ] **Step 9: store に update メソッドの実装を追加**
  同ファイルの `load` メソッド実装の直後(`clear()` の前)に `update` を追加する。`old_string`:
  ```typescript
      } finally {
        loading = false;
      }
    },
    clear() {
      notebook = null;
  ```
  `new_string`:
  ```typescript
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
  ```

- [ ] **Step 10: 型/ビルド健全性を確認(store + 型変更)**
  Run: `cd apps/web && npm run check`
  Expected: PASS(`svelte-check` で 0 errors。`update` の戻り型と `NotebookUpdate` の null 許容が通る)。

- [ ] **Step 11: commit(フロント API/型/store)**
  Run:
  ```
  git add apps/web/src/lib/api/types.ts apps/web/src/lib/stores/currentNotebook.svelte.ts
  git commit -m "feat(web): add currentNotebookStore.update and allow null default_model"
  ```

- [ ] **Step 12: detail ページ — import と onMount でモデル/設定をロード**
  `apps/web/src/routes/notebooks/[id]/+page.svelte` の `<script>` 冒頭の import 群に `modelsStore` / `settingsStore` / `pushToast` を追加する。`old_string`:
  ```typescript
    import { currentNotebookStore } from '$lib/stores/currentNotebook.svelte';
    import { conversationStore } from '$lib/stores/conversation.svelte';
    import { eventsStore } from '$lib/stores/events.svelte';
  ```
  `new_string`:
  ```typescript
    import { currentNotebookStore } from '$lib/stores/currentNotebook.svelte';
    import { modelsStore } from '$lib/stores/models.svelte';
    import { settingsStore } from '$lib/stores/settings.svelte';
    import { conversationStore } from '$lib/stores/conversation.svelte';
    import { eventsStore } from '$lib/stores/events.svelte';
    import { pushToast } from '$lib/components/Toast.svelte';
  ```

- [ ] **Step 13: detail ページ — onMount でモデル/設定をロード**
  既存 `onMount` 内、`await currentNotebookStore.load(data.notebookId);` の直後に並列ロードを追加する(`models`/`settings` は他ルートで都度 `load()` する方式に倣う。detail では未ロードのため明示ロードが必要)。`old_string`:
  ```typescript
      await currentNotebookStore.load(data.notebookId);
      eventsStore.start(data.notebookId);
  ```
  `new_string`:
  ```typescript
      await currentNotebookStore.load(data.notebookId);
      // モデルピッカー用: モデル一覧と全体既定名を取得(失敗してもページは描画継続)
      void modelsStore.load();
      void settingsStore.load();
      eventsStore.start(data.notebookId);
  ```

- [ ] **Step 14: detail ページ — 派生値とハンドラを追加**
  `<script>` 内、`onMount(...)` の宣言の**前**(`unbindShortcuts` 宣言の直後あたり、`$effect` の前)に派生値と `onModelChange` ハンドラを追加する。`old_string`:
  ```typescript
    let unbindShortcuts: (() => void) | null = null;

    // when notebook changes, reset conversation (clear messages, drop current conv ref)
    $effect(() => {
  ```
  `new_string`:
  ```typescript
    let unbindShortcuts: (() => void) | null = null;

    // 全体既定名(設定未ロード時は空文字)
    const globalDefault = $derived(settingsStore.settings?.ollama.default_model ?? '');
    // チャット可能モデルのみ(kind が chat / both)
    const chatModels = $derived(
      modelsStore.models.filter((m) => m.kind === 'chat' || m.kind === 'both'),
    );
    // <select> の現在値。null(=既定)は空文字 '' を選択。
    const selectedModel = $derived(currentNotebookStore.notebook?.default_model ?? '');

    async function onModelChange(e: Event) {
      const value = (e.currentTarget as HTMLSelectElement).value;
      const next: string | null = value === '' ? null : value;
      const prev = currentNotebookStore.notebook?.default_model ?? null;
      if (next === prev) return;
      try {
        await currentNotebookStore.update({ default_model: next });
        pushToast(
          next === null
            ? `このノートのモデルを既定（${globalDefault}）に戻しました`
            : `このノートのモデルを ${next} に変更しました`,
          'success',
        );
      } catch (err) {
        pushToast(err instanceof Error ? err.message : String(err), 'error');
      }
    }

    // when notebook changes, reset conversation (clear messages, drop current conv ref)
    $effect(() => {
  ```

- [ ] **Step 15: detail ページ — .topbar に <select> を追加**
  `.topbar` の `<h2>` の直後にモデルピッカーを追加する。`select` の `value` は `selectedModel`(双方向ではなく `value=`＋`onchange` の制御コンポーネント方式。Svelte 5 で派生値を読取専用に保つため `bind:` は使わない)。`old_string`:
  ```svelte
      <h2>{currentNotebookStore.notebook?.name ?? '読み込み中…'}</h2>
    </div>
  ```
  `new_string`:
  ```svelte
      <h2>{currentNotebookStore.notebook?.name ?? '読み込み中…'}</h2>
      {#if currentNotebookStore.notebook}
        <label class="model-pick">
          <span class="model-pick-label">このノートのモデル</span>
          <select value={selectedModel} onchange={onModelChange}>
            <option value="">既定（{globalDefault || '全体既定'}）</option>
            {#each chatModels as m (m.name)}
              <option value={m.name}>{m.name}</option>
            {/each}
          </select>
        </label>
      {/if}
    </div>
  ```

- [ ] **Step 16: detail ページ — スタイル追加**
  `<style>` ブロック内、`.topbar h2 { ... }` ルールの直後にピッカー用スタイルを追加する。`old_string`:
  ```css
    .topbar h2 {
      margin: 0;
      font-size: 16px;
    }
  ```
  `new_string`:
  ```css
    .topbar h2 {
      margin: 0;
      font-size: 16px;
    }
    .model-pick {
      display: inline-flex;
      align-items: center;
      gap: var(--space-2);
      margin-left: auto;
    }
    .model-pick-label {
      font-size: 11px;
      color: var(--color-fg-muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .model-pick select {
      font-size: 12px;
      padding: 2px var(--space-2);
      border: 1px solid var(--color-border);
      border-radius: var(--radius-sm);
      background: var(--color-bg);
      color: var(--color-fg);
      max-width: 220px;
    }
  ```

- [ ] **Step 17: 型/ビルド健全性を確認(detail ページ)**
  Run: `cd apps/web && npm run check`
  Expected: PASS(0 errors。`ModelInfo.kind`(Task 1 由来)、`onModelChange` の `HTMLSelectElement` キャスト、派生値の型が解決する)。
  - 失敗ケース: `Property 'kind' does not exist on type 'ModelInfo'` が出たら Task 1(`ModelInfo` への `kind` 追加)が未完了。その場合は Task 1 完了を待つ(本タスクは Task 1 に依存)。

- [ ] **Step 18: 本番ビルドが通ることを確認(任意・型超えのビルド健全性)**
  Run: `cd apps/web && npm run build`
  Expected: PASS(`vite build` がエラーなく `dist/` を生成)。
  注意: このビルドは `dist/` を空にするため、追跡対象の `apps/web/dist/.gitkeep`(`apps/web/.gitignore` で `!dist/.gitkeep` として保護)が削除される。次ステップで必ず復元する。

- [ ] **Step 19: dist/.gitkeep 既知問題のケア(commit 前)**
  ビルドで消えた `.gitkeep` を復元し、`dist/` のビルド成果物を誤ってステージしないことを確認する。
  Run:
  ```
  git checkout -- apps/web/dist/.gitkeep
  git status --porcelain apps/web/dist
  ```
  Expected: `git status --porcelain apps/web/dist` の出力が**空**(ビルド成果物は `dist/*` で gitignore 済み、`.gitkeep` は復元済みで差分なし)。出力に何か出る場合は `dist/` 配下を `git add` しないこと(`git restore --staged apps/web/dist` で退避)。

- [ ] **Step 20: commit(detail ページ UI)**
  Run:
  ```
  git add apps/web/src/routes/notebooks/[id]/+page.svelte
  git commit -m "feat(web): add per-notebook model picker to notebook detail topbar"
  ```

- [ ] **Step 21: 視覚検証ゲート(Playwright・スクショ必須)— このタスクの PASS 条件**
  自動 `npm run check` の GREEN だけでは GUI のビジュアル回帰(レイアウト崩れ・ピッカー非表示)を検出できないため、実機スクショ検証を必須とする(プロジェクト方針: GUI 変更は自動 GREEN だけで PASS 禁止)。
  手順:
  1. バックエンド起動: `uv run --extra recording uvicorn apps.api.main:app --port 8765`
  2. フロント dev 起動: `cd apps/web && npm run dev`(`http://localhost:5173`、API は :8765 へプロキシ)。BE/FE を変更したら BE は uvicorn 再起動・FE は dev サーバ反映を待つこと。
  3. Playwright MCP で `http://localhost:5173/notebooks/<既存ノートID>` を開く。`browser_snapshot` で `.topbar` 内に「このノートのモデル」ラベル + `<select>` が表示されることを確認。`browser_take_screenshot` を取得。
  4. `<select>` を chat/both のモデルに変更 → 成功トースト表示 + ページリロード後も選択が保持される(永続化)ことをスクショで確認。
  5. 先頭「既定（…）」を選択 → `default_model=null` 送信 → リロード後も「既定」が選択状態(全体既定にフォールバック)であることをスクショで確認。
  6. embedding 専用モデルが `<select>` に**出ていない**(chat/both のみ)ことを確認。
  PASS 条件: 上記 3〜6 のスクショがすべて期待通り(ピッカー表示・切替反映・null クリア・embedding 除外)。1 つでも崩れていれば NG として修正してから再検証。

- [ ] **Step 22: 視覚 NG 時のみ self-fix(最大 3 回)**
  スクショで不具合(ピッカー非表示・レイアウト崩れ・トースト未表示・null クリア不能等)があれば原因を特定し、該当ステップ(13〜16 の UI / 9 の store / 4 の router)を修正 → 再ビルド(Step 18〜19 の `.gitkeep` ケア込み)→ 再スクショ。3 回で解消しない場合は親オーケストレータへ blocker として報告する(推測修正の無限ループを避ける)。

依存メモ(後続/前提):
- 前提: Task 1 が `apps/web/src/lib/api/types.ts` の `ModelInfo` に `kind` を追加済みであること(Step 14 の `chatModels` フィルタが依存)。未完なら Step 17 が失敗する。
- 本タスクが追加する `currentNotebookStore.update(patch)` と「PATCH の null クリア」挙動は、Task 3(全体既定 `<select>`)等が同 store を再利用する場合の土台となる。

---

### Task 5: 埋め込み次元の検出と VectorStore 拡張・dim 動的化

**Files:**
- Modify: `core/ollama/gateway.py` (末尾に `probe_embedding_dim` を追加)
- Modify: `core/storage/vector_store.py` (`VectorStore.collection_dim()` / `recreate_collection()` を追加)
- Modify: `core/config.py:9-20` (`OllamaSettings` に `embedding_dim: int = 1024` を追加)
- Modify: `apps/api/dependencies.py:18,39` (`_EMBEDDING_DIM` ハードコード撤廃、dim 動的解決)
- Modify: `apps/api/routers/models.py:14-47` (`embedding/both` モデルに `embedding_dim` を付与)
- Modify: `apps/api/schemas/settings.py` (`OllamaSettingsSchema` に `embedding_dim: int | None = None` を追加)
- Modify: `apps/api/routers/settings.py` (`get_settings` の `OllamaSettingsSchema` 構築に `embedding_dim=ctx.vector_store.collection_dim()` を渡す)
- Modify: `apps/web/src/lib/api/types.ts:102-108` (`ModelInfo` に `embedding_dim?: number | null`)
- Test: `tests/unit/test_probe_embedding_dim.py` (新規・ユニット)
- Test: `tests/integration/test_vector_store_dim.py` (新規・qdrant ローカル統合)
- Test: `tests/unit/test_build_context_dim.py` (新規・ユニット、settings.json あり/なし)
- Test: `tests/integration/test_api/test_settings_api.py` (既存に `embedding_dim` 露出テストを 1 ケース追記)

**Interfaces:**
- Consumes (Task 1 の `classify_kind` 想定。本タスクでは未確定でも動くよう models.py 側は防御的に扱う):
  - `classify_kind(*, capabilities: list[str], name: str) -> str`(返り値 `"chat" | "embedding" | "both" | "unknown"`)— Task 1 で `core/ollama/models_info.py` に追加済みであれば import して利用。**未実装の場合に備え、models.py のステップでは import を try で囲み、無ければ名前ヒューリスティックにフォールバックする実装を本タスク内に同梱する**(下記 Step 9 参照)。
  - `OllamaGateway.embed(*, model: str, text: str) -> list[float]`(既存・確認済み `core/ollama/gateway.py:34`)。
- Produces (Task 7 / Task 8 が利用):
  - `async probe_embedding_dim(gateway: OllamaGateway, model: str) -> int`(`core/ollama/gateway.py`、プロセス内キャッシュ付き)。
  - `VectorStore.collection_dim() -> int | None`(`core/storage/vector_store.py`)。
  - `VectorStore.recreate_collection(dim: int) -> None`(同上、既存 collection を drop してから COSINE で再作成)。
  - **`GET /api/settings` の `ollama` に `embedding_dim`(= `ctx.vector_store.collection_dim()`、collection 無しは `null`)を露出**(Step 13b)。Task 8 の次元警告バナーが読む現行次元 `curDim` の供給元。フロント `OllamaSettings.embedding_dim: number | null` と整合させる。

---

- [ ] **Step 1: probe_embedding_dim の失敗テストを書く**

新規ファイル `tests/unit/test_probe_embedding_dim.py` を作成する。fake gateway は `embed` の返りベクトル長を可変にし、呼び出し回数を記録してキャッシュ動作を検証する。

```python
import pytest

from core.ollama.gateway import probe_embedding_dim, reset_embedding_dim_cache


class FakeGateway:
    def __init__(self, dim: int) -> None:
        self._dim = dim
        self.calls: list[str] = []

    async def embed(self, *, model: str, text: str) -> list[float]:
        self.calls.append(model)
        return [0.0] * self._dim


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_embedding_dim_cache()
    yield
    reset_embedding_dim_cache()


@pytest.mark.asyncio
async def test_probe_returns_vector_length():
    gw = FakeGateway(dim=768)
    dim = await probe_embedding_dim(gw, "nomic-embed-text")
    assert dim == 768
    assert gw.calls == ["nomic-embed-text"]


@pytest.mark.asyncio
async def test_probe_caches_per_model():
    gw = FakeGateway(dim=1024)
    first = await probe_embedding_dim(gw, "bge-m3")
    second = await probe_embedding_dim(gw, "bge-m3")
    assert first == second == 1024
    # キャッシュヒットで 2 回目は embed を呼ばない
    assert gw.calls == ["bge-m3"]


@pytest.mark.asyncio
async def test_probe_distinct_models_not_shared():
    gw = FakeGateway(dim=512)
    await probe_embedding_dim(gw, "model-a")
    await probe_embedding_dim(gw, "model-b")
    assert gw.calls == ["model-a", "model-b"]
```

- [ ] **Step 2: 失敗を確認する**
  - Run: `uv run pytest tests/unit/test_probe_embedding_dim.py -v`
  - Expected: FAIL(`ImportError: cannot import name 'probe_embedding_dim'`)

- [ ] **Step 3: probe_embedding_dim を最小実装する**

`core/ollama/gateway.py` の末尾(`OllamaGateway` クラスの後)に以下を追加する。`Protocol` で gateway を緩く型付けし、プロセス内 dict キャッシュを持つ。

```python
class _GatewayLike(Protocol):
    async def embed(self, *, model: str, text: str) -> list[float]: ...


_EMBEDDING_DIM_CACHE: dict[str, int] = {}


def reset_embedding_dim_cache() -> None:
    """テスト用: プロセス内キャッシュをクリアする。"""
    _EMBEDDING_DIM_CACHE.clear()


async def probe_embedding_dim(gateway: _GatewayLike, model: str) -> int:
    """短文を埋め込み、返りベクトルの長さ(次元)を返す。

    結果はプロセス内 dict にモデル名でキャッシュする。同一モデルの
    2 回目以降は Ollama を叩かずキャッシュ値を返す。
    """
    cached = _EMBEDDING_DIM_CACHE.get(model)
    if cached is not None:
        return cached
    vector = await gateway.embed(model=model, text="x")
    dim = len(vector)
    _EMBEDDING_DIM_CACHE[model] = dim
    return dim
```

- [ ] **Step 4: 成功を確認してコミットする**
  - Run: `uv run pytest tests/unit/test_probe_embedding_dim.py -v`
  - Expected: PASS(3 件)
  - Run: `git add core/ollama/gateway.py tests/unit/test_probe_embedding_dim.py`
  - Run: `git commit -m "feat(ollama): add probe_embedding_dim with per-model cache"`

- [ ] **Step 5: collection_dim / recreate_collection の失敗テストを書く**

新規ファイル `tests/integration/test_vector_store_dim.py` を作成する。既存 `tests/integration/test_vector_store.py` の作法に倣い `@pytest.mark.qdrant` + `tmp_path` を使う。

```python
import pytest

from core.storage.vector_store import ChunkVector, VectorStore


@pytest.mark.qdrant
def test_collection_dim_none_before_ensure(tmp_path):
    vs = VectorStore(path=tmp_path / "qdrant", dim=4)
    # collection 未作成 -> None
    assert vs.collection_dim() is None


@pytest.mark.qdrant
def test_collection_dim_reports_size(tmp_path):
    vs = VectorStore(path=tmp_path / "qdrant", dim=4)
    vs.ensure_collection()
    assert vs.collection_dim() == 4


@pytest.mark.qdrant
def test_recreate_collection_changes_dim_and_drops_points(tmp_path):
    vs = VectorStore(path=tmp_path / "qdrant", dim=4)
    vs.ensure_collection()
    vs.upsert(
        [
            ChunkVector(
                id="a" * 26,
                vector=[1, 0, 0, 0],
                notebook_id="NB",
                source_id="S",
                source_kind="md",
                page=None,
                heading_path=None,
                ord=0,
            )
        ]
    )
    assert vs.collection_dim() == 4
    # 再作成で新しい dim、既存ポイントは消える
    vs.recreate_collection(8)
    assert vs.collection_dim() == 8
    hits = vs.search(query=[0.0] * 8, notebook_id="NB", limit=10)
    assert hits == []
    # 新 dim で upsert/search が成立する
    vs.upsert(
        [
            ChunkVector(
                id="b" * 26,
                vector=[1, 0, 0, 0, 0, 0, 0, 0],
                notebook_id="NB",
                source_id="S2",
                source_kind="md",
                page=None,
                heading_path=None,
                ord=0,
            )
        ]
    )
    hits2 = vs.search(query=[1, 0, 0, 0, 0, 0, 0, 0], notebook_id="NB", limit=10)
    assert [h.id for h in hits2] == ["b" * 26]
```

- [ ] **Step 6: 失敗を確認する**
  - Run: `uv run pytest tests/integration/test_vector_store_dim.py -v -m qdrant`
  - Expected: FAIL(`AttributeError: 'VectorStore' object has no attribute 'collection_dim'`)

- [ ] **Step 7: collection_dim / recreate_collection を実装する**

`core/storage/vector_store.py` の `VectorStore` クラス内、`ensure_collection` の直後に以下 2 メソッドを追加する(qdrant の戻り構造 `get_collection(...).config.params.vectors.size` は実機で確認済み)。

```python
    def collection_dim(self) -> int | None:
        """現行 collection のベクトル次元。collection が無ければ None。"""
        existing = {c.name for c in self._client.get_collections().collections}
        if COLLECTION not in existing:
            return None
        info = self._client.get_collection(COLLECTION)
        return info.config.params.vectors.size

    def recreate_collection(self, dim: int) -> None:
        """既存 collection を drop してから dim 次元(COSINE)で作り直す。

        全チャンクの再インデックス用。既存 collection が無くても新規作成する。
        以降この VectorStore は新しい dim で動作する。
        """
        existing = {c.name for c in self._client.get_collections().collections}
        if COLLECTION in existing:
            self._client.delete_collection(collection_name=COLLECTION)
        self._client.create_collection(
            collection_name=COLLECTION,
            vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
        )
        self._dim = dim
```

- [ ] **Step 8: 成功を確認してコミットする**
  - Run: `uv run pytest tests/integration/test_vector_store_dim.py -v -m qdrant`
  - Expected: PASS(3 件)
  - Run: `git add core/storage/vector_store.py tests/integration/test_vector_store_dim.py`
  - Run: `git commit -m "feat(vector-store): add collection_dim and recreate_collection"`

- [ ] **Step 9: models.py に embedding_dim 付与の失敗テストを書く**

まず既存 models のテストファイル名を確認する。
  - Run: `ls tests/integration/test_api/ | grep -i model`
  - Expected: `test_models.py` 等が見つかる(無ければ新規 `tests/integration/test_api/test_models_embedding_dim.py` を作る)。

新規ファイル `tests/integration/test_api/test_models_embedding_dim.py` を作成する。統合テスト規約(`TestClient(create_app())` + `NOTEBOOK_OLLAMA_DATA_DIR` monkeypatch、`ctx = client.app.state.ctx`)に従い、Ollama を叩かないよう `OllamaClient` をモンキーパッチして `list_tags`/`show` を fake にし、gateway の `embed` も fake にする。`embed` は埋め込みモデル名のときだけ次元を返す。

```python
import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        yield c


class _FakeOllamaClient:
    """list_models が使う raw client を差し替えるためのスタブ。"""

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def list_tags(self):
        return [
            {"name": "qwen2.5:14b", "size": 100, "details": {"family": "qwen"}},
            {"name": "bge-m3", "size": 50, "details": {"family": "bert"}},
        ]

    async def show(self, model):
        if model == "bge-m3":
            return {"capabilities": ["embedding"], "parameters": ""}
        return {"capabilities": ["completion"], "parameters": "num_ctx 8192"}


def test_models_embedding_dim_for_embedding_models(client, monkeypatch):
    # list_models が new する raw client を fake に差し替え
    monkeypatch.setattr("apps.api.routers.models.OllamaClient", _FakeOllamaClient)

    # gateway.embed を fake 化(埋め込みモデルだけ 1024 を返す)
    async def fake_embed(*, model, text):
        assert model == "bge-m3"
        return [0.0] * 1024

    client.app.state.ctx.ollama.embed = fake_embed  # type: ignore[method-assign]

    resp = client.get("/api/models")
    assert resp.status_code == 200
    by_name = {m["name"]: m for m in resp.json()["models"]}
    # 埋め込みモデルには probe 由来の dim が付く
    assert by_name["bge-m3"]["embedding_dim"] == 1024
    # チャットモデルは null
    assert by_name["qwen2.5:14b"]["embedding_dim"] is None
```

- [ ] **Step 10: 失敗を確認する**
  - Run: `uv run pytest tests/integration/test_api/test_models_embedding_dim.py -v`
  - Expected: FAIL(`KeyError: 'embedding_dim'`)

- [ ] **Step 11: models.py に embedding_dim 付与を実装する**

`apps/api/routers/models.py` を全面更新する。`kind` 判定は Task 1 の `classify_kind` を優先し、未実装でも落ちないよう import を try で囲んでローカルフォールバックを用意する。`embedding/both` のモデルにのみ `probe_embedding_dim` を呼び、失敗時は `None`。

```python
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from core.ollama.client import OllamaClient
from core.ollama.gateway import probe_embedding_dim
from core.ollama.models_info import classify_recommendation, parse_context_window
from core.storage import notebooks_repo

router = APIRouter(prefix="/api", tags=["models"])

_EMBED_NAME_HINTS = ("embed", "bge", "nomic-embed", "mxbai", "snowflake-arctic-embed", "all-minilm")


def _classify_kind(*, capabilities: list[str], name: str) -> str:
    """Task 1 の classify_kind があればそれを使い、無ければローカル判定。"""
    try:
        from core.ollama.models_info import classify_kind  # type: ignore[attr-defined]

        return classify_kind(capabilities=capabilities, name=name)
    except (ImportError, AttributeError):
        caps = {c.lower() for c in capabilities}
        has_embed = "embedding" in caps
        has_chat = "completion" in caps or "chat" in caps
        if has_embed and has_chat:
            return "both"
        if has_embed:
            return "embedding"
        if has_chat:
            return "chat"
        lower = name.lower()
        if any(h in lower for h in _EMBED_NAME_HINTS):
            return "embedding"
        return "chat"


@router.get("/models")
async def list_models(request: Request) -> dict[str, Any]:
    ctx = request.app.state.ctx
    client = OllamaClient(
        endpoint=ctx.config.ollama.endpoint,
        timeout=ctx.config.ollama.request_timeout_seconds,
    )
    tags = await client.list_tags()
    models: list[dict[str, Any]] = []
    for tag in tags:
        name = tag["name"]
        details = tag.get("details", {}) or {}
        show = await client.show(name)
        params_str = show.get("parameters", "")
        ctx_window = parse_context_window(params_str)
        capabilities = show.get("capabilities", []) or []
        kind = _classify_kind(capabilities=capabilities, name=name)
        embedding_dim: int | None = None
        if kind in ("embedding", "both"):
            try:
                embedding_dim = await probe_embedding_dim(ctx.ollama, name)
            except Exception:
                embedding_dim = None
        models.append(
            {
                "name": name,
                "size_bytes": tag.get("size"),
                "context_window": ctx_window,
                "modified_at": tag.get("modified_at"),
                "kind": kind,
                "embedding_dim": embedding_dim,
                "recommended_for": classify_recommendation(
                    name=name,
                    family=details.get("family", ""),
                    parameter_size=details.get("parameter_size", ""),
                    context_window=ctx_window,
                ),
            }
        )
    notebooks = notebooks_repo.list_notebooks(ctx.conn)
    defaults = [
        {"notebook_id": n.id, "name": n.name, "default_model": n.default_model} for n in notebooks
    ]
    return {"models": models, "defaults_by_notebook": defaults}
```

> 注: `kind` キーは Task 1 のスコープだが、`_classify_kind` のローカルフォールバックにより本タスク単独でも整合する。Task 1 が `classify_kind` を追加すれば自動的にそちらが使われる。

- [ ] **Step 12: 成功を確認してコミットする**
  - Run: `uv run pytest tests/integration/test_api/test_models_embedding_dim.py -v`
  - Expected: PASS(1 件)
  - Run: `uv run pytest tests/integration/test_api -k model -v`
  - Expected: PASS(既存 models テストも壊れていない)
  - Run: `git add apps/api/routers/models.py tests/integration/test_api/test_models_embedding_dim.py`
  - Run: `git commit -m "feat(models): expose kind and embedding_dim in /api/models"`

- [ ] **Step 13: config に embedding_dim を追加する**

`core/config.py` の `OllamaSettings`(`embedding_options` 行の直前)に永続化用の `embedding_dim` を追加する。

```python
    embedding_dim: int = 1024
```

挿入位置:

```python
class OllamaSettings(BaseModel):
    endpoint: str = "http://localhost:11434"
    default_model: str = "qwen2.5:14b"
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024
    request_timeout_seconds: float = 120.0
```

(既存の `embedding_options` 等はそのまま残す。)

- [ ] **Step 13b: `GET /api/settings` の ollama に `embedding_dim` を露出する(失敗テスト → 実装)**

`GET /api/settings` のレスポンス `ollama` に現行 collection 次元(`embedding_dim`)を載せる。これは Task 8 の次元警告バナー(設計 (C) 中核)が現行次元 `curDim` を読む唯一の供給元であり、ここで露出しないと警告が永久に出ない。

まず失敗テストを `tests/integration/test_api/test_settings_api.py` の末尾に追記する(`embedding_dim` がレスポンスに無ければ `KeyError`/欠落で失敗)。

```python
def test_get_settings_exposes_embedding_dim(client):
    # 既定 collection は 1024 次元(bge-m3)で作成される
    r = client.get("/api/settings")
    assert r.status_code == 200
    ollama = r.json()["ollama"]
    assert "embedding_dim" in ollama
    # build_context が ensure_collection 済みのため現行次元が返る
    assert ollama["embedding_dim"] == 1024
```

> 注: この `client` フィクスチャは既存 `tests/integration/test_api/test_settings_api.py` のものを流用する(`TestClient(create_app())` + `NOTEBOOK_OLLAMA_DATA_DIR` monkeypatch)。フィクスチャ名/作法が異なる場合は同ファイル冒頭の既存フィクスチャに合わせること。

Run: `uv run pytest tests/integration/test_api/test_settings_api.py::test_get_settings_exposes_embedding_dim -v`
Expected: FAIL(`embedding_dim` がレスポンスに無く `KeyError` / `assert 'embedding_dim' in ollama` で失敗)。

次にスキーマへ `embedding_dim` を追加する。`apps/api/schemas/settings.py` の `OllamaSettingsSchema`(現状 `endpoint`/`default_model`/`embedding_model` の 3 フィールド)を置換する。`old_string`:
```python
class OllamaSettingsSchema(BaseModel):
    endpoint: str
    default_model: str
    embedding_model: str
```
`new_string`:
```python
class OllamaSettingsSchema(BaseModel):
    endpoint: str
    default_model: str
    embedding_model: str
    embedding_dim: int | None = None
```

続いて `apps/api/routers/settings.py` の `get_settings` の `OllamaSettingsSchema(...)` 構築に `embedding_dim` を渡す。`old_string`:
```python
        ollama=OllamaSettingsSchema(
            endpoint=cfg.ollama.endpoint,
            default_model=cfg.ollama.default_model,
            embedding_model=cfg.ollama.embedding_model,
        ),
```
`new_string`:
```python
        ollama=OllamaSettingsSchema(
            endpoint=cfg.ollama.endpoint,
            default_model=cfg.ollama.default_model,
            embedding_model=cfg.ollama.embedding_model,
            embedding_dim=request.app.state.ctx.vector_store.collection_dim(),
        ),
```

> 注: `collection_dim()` は本 Task 5 Step 7 で `VectorStore` に追加済みであること(順序: Step 7 → 本 Step)。collection 未作成時は `None` を返すため `embedding_dim: int | None` と整合する。`request.app.state.ctx.vector_store` は `AppContext.vector_store`(`apps/api/dependencies.py` で確認済み)。

Run: `uv run pytest tests/integration/test_api/test_settings_api.py -v`
Expected: PASS(新規 `test_get_settings_exposes_embedding_dim` + 既存 settings テストすべて green。`AppSettingsSchema` への `embedding_dim` 追加はデフォルト `None` のため既存テストを壊さない)。

コミット:
```bash
git add apps/api/schemas/settings.py apps/api/routers/settings.py tests/integration/test_api/test_settings_api.py
git commit -m "feat(settings): expose embedding_dim (collection_dim) via GET /api/settings"
```

- [ ] **Step 14: build_context の dim 解決の失敗テストを書く**

新規ファイル `tests/unit/test_build_context_dim.py` を作成する。Ollama を叩かず、settings.json の有無 / 既存 collection の有無で `vector_store.collection_dim()` がどう決まるかを検証する。`AppConfig(data_dir=tmp_path)` を直接組み、`build_context` を呼ぶ(ネットワーク不要。`build_context` は Ollama を叩かない方針)。

```python
import json

import pytest

from apps.api.dependencies import build_context
from core.config import AppConfig
from core.settings_store import settings_path


def _make_config(tmp_path):
    return AppConfig(data_dir=tmp_path)


def test_default_dim_when_no_settings_and_no_collection(tmp_path):
    cfg = _make_config(tmp_path)
    ctx = build_context(cfg)
    try:
        assert ctx.vector_store.collection_dim() == 1024
    finally:
        ctx.vector_store.close()


def test_dim_from_settings_json_when_no_collection(tmp_path):
    cfg = _make_config(tmp_path)
    cfg.ensure_dirs()
    settings_path(cfg.data_dir).write_text(
        json.dumps({"ollama": {"embedding_dim": 768}}), encoding="utf-8"
    )
    ctx = build_context(cfg)
    try:
        assert ctx.vector_store.collection_dim() == 768
    finally:
        ctx.vector_store.close()


def test_existing_collection_dim_wins_over_settings(tmp_path):
    # 既存 collection を 512 次元で先に作る
    from core.storage.vector_store import VectorStore

    pre = VectorStore(path=tmp_path / "qdrant", dim=512)
    pre.ensure_collection()
    pre.close()

    cfg = _make_config(tmp_path)
    cfg.ensure_dirs()
    # settings は別の dim を主張するが、既存 collection を優先する
    settings_path(cfg.data_dir).write_text(
        json.dumps({"ollama": {"embedding_dim": 768}}), encoding="utf-8"
    )
    ctx = build_context(cfg)
    try:
        assert ctx.vector_store.collection_dim() == 512
    finally:
        ctx.vector_store.close()
```

> 注: `AppConfig.qdrant_path` は `data_dir / "qdrant"`(確認済み `core/config.py:92`)。上の事前 collection は同じパスに作るため `build_context` がそれを検出する。

- [ ] **Step 15: 失敗を確認する**
  - Run: `uv run pytest tests/unit/test_build_context_dim.py -v`
  - Expected: FAIL(`build_context` がまだ `_EMBEDDING_DIM=1024` 固定のため、settings.json の 768 ケースで `1024 != 768`、既存 collection 優先ケースは `1024 != 512`)

- [ ] **Step 16: dependencies.py の dim 動的化を実装する**

`apps/api/dependencies.py` を更新する。`_EMBEDDING_DIM` 定数を撤廃し、`load_overrides` で settings.json を読んで dim を解決するヘルパを追加。起動時に Ollama は叩かない。

まず import を追加する(`from core.storage.vector_store import VectorStore` の行群に隣接):

```python
from core.settings_store import load_overrides
from core.storage.database import connect, migrate
from core.storage.vector_store import VectorStore
```

`_EMBEDDING_DIM = 1024  # bge-m3` の行を削除し、その位置に dim 解決ヘルパを追加する:

```python
_DEFAULT_EMBEDDING_DIM = 1024  # bge-m3


def _resolve_embedding_dim(config: AppConfig, vs: VectorStore) -> int:
    """起動時の VectorStore 次元を決める(Ollama は叩かない)。

    1. 既存 collection があればその次元を採用(ensure_collection は既存尊重)。
    2. 無ければ settings.json の ollama.embedding_dim を採用。
    3. それも無ければ既定 1024。
    """
    existing = vs.collection_dim()
    if existing is not None:
        return existing
    ov = load_overrides(config.data_dir)
    ollama_ov = ov.get("ollama")
    if isinstance(ollama_ov, dict):
        dim = ollama_ov.get("embedding_dim")
        if isinstance(dim, int) and dim > 0:
            return dim
    return _DEFAULT_EMBEDDING_DIM
```

`build_context` 冒頭の VectorStore 構築部(現 38-40 行)を次に差し替える:

```python
    config.ensure_dirs()
    conn = connect(config.metadata_db_path)
    migrate(conn)
    vs = VectorStore(path=config.qdrant_path, dim=_DEFAULT_EMBEDDING_DIM)
    resolved_dim = _resolve_embedding_dim(config, vs)
    vs = VectorStore(path=config.qdrant_path, dim=resolved_dim)
    vs.ensure_collection()
```

> 設計上の要点: 1 個目の `VectorStore` は `collection_dim()` の問い合わせ用(`QdrantClient(path=...)` はディレクトリをロックするため、判定後に `close()` してから本番用を作り直す)。次の Step 17 でこのリーク防止を加える。

- [ ] **Step 17: collection 問い合わせ用 store をクローズしてから本番 store を作る**

Step 16 のコードは QdrantClient のローカルロック(同一パスを 2 重に開けない)に抵触する。`_resolve_embedding_dim` を「問い合わせ用 store を内部で開いて閉じる」形に変更し、`build_context` 側は本番 store を 1 つだけ作る。`apps/api/dependencies.py` を最終形に整える:

`_resolve_embedding_dim` を次に差し替える:

```python
def _resolve_embedding_dim(config: AppConfig) -> int:
    """起動時の VectorStore 次元を決める(Ollama は叩かない)。

    1. 既存 collection があればその次元を採用(問い合わせ用 store を開いて閉じる)。
    2. 無ければ settings.json の ollama.embedding_dim を採用。
    3. それも無ければ既定 1024。
    """
    probe_store = VectorStore(path=config.qdrant_path, dim=_DEFAULT_EMBEDDING_DIM)
    try:
        existing = probe_store.collection_dim()
    finally:
        probe_store.close()
    if existing is not None:
        return existing
    ov = load_overrides(config.data_dir)
    ollama_ov = ov.get("ollama")
    if isinstance(ollama_ov, dict):
        dim = ollama_ov.get("embedding_dim")
        if isinstance(dim, int) and dim > 0:
            return dim
    return _DEFAULT_EMBEDDING_DIM
```

`build_context` の VectorStore 構築部を次に差し替える(問い合わせ用 store は `_resolve_embedding_dim` 内で閉じ済み):

```python
    config.ensure_dirs()
    conn = connect(config.metadata_db_path)
    migrate(conn)
    resolved_dim = _resolve_embedding_dim(config)
    vs = VectorStore(path=config.qdrant_path, dim=resolved_dim)
    vs.ensure_collection()
```

- [ ] **Step 18: build_context の dim 解決テストを通す**
  - Run: `uv run pytest tests/unit/test_build_context_dim.py -v`
  - Expected: PASS(3 件)

- [ ] **Step 19: 既存テストの非回帰を確認する**
  - Run: `uv run pytest tests/integration -k "vector or pipeline or search or recording" -q`
  - Expected: PASS(`build_context` / VectorStore を使う既存統合テストが壊れていない。`-m qdrant` を要するものは環境に応じ skip/pass)
  - Run: `uv run pytest tests/unit -q`
  - Expected: PASS

- [ ] **Step 20: config と dependencies をコミットする**
  - Run: `git add core/config.py apps/api/dependencies.py tests/unit/test_build_context_dim.py`
  - Run: `git commit -m "feat(deps): resolve VectorStore dim from collection or settings.json"`

- [ ] **Step 21: フロント ModelInfo 型に embedding_dim を追加する**

`apps/web/src/lib/api/types.ts` の `ModelInfo` を更新する。`kind`(Task 1 のスコープ)と衝突しないよう、本タスクでは `embedding_dim` のみ追加する(`kind` の型追加は Task 1 が担当)。

```typescript
export interface ModelInfo {
  name: string;
  size_bytes: number | null;
  context_window: number | null;
  modified_at: string;
  recommended_for: string[];
  embedding_dim?: number | null;
}
```

- [ ] **Step 22: フロントの型チェックを確認してコミットする**
  - Run: `cd apps/web && npm run check`
  - Expected: PASS(型エラーなし。`embedding_dim` はオプショナルなので既存呼び出しに影響しない)
  - Run: `git add apps/web/src/lib/api/types.ts`
  - Run: `git commit -m "feat(web): add embedding_dim to ModelInfo type"`

---

確認した実コード根拠(推測でないこと):
- `core/storage/vector_store.py:60-72`(`VectorStore.__init__` / `ensure_collection`、`self._client` / `self._dim` / `COLLECTION` / `qm`)。
- qdrant `get_collection(COLLECTION).config.params.vectors.size` は実機で `7` を返すことを確認(`CollectionInfo`)。
- `core/ollama/gateway.py:34`(`OllamaGateway.embed(*, model, text) -> list[float]`、`probe_embedding_dim` を末尾追加)。
- `apps/api/dependencies.py:18,39`(`_EMBEDDING_DIM=1024`、`VectorStore(dim=...)`、各サービスへ `config.ollama.embedding_model` を値渡し)。
- `core/settings_store.py:17`(`load_overrides(data_dir) -> dict`、Ollama 非依存)。
- `apps/api/routers/models.py:14-47`(`list_models`、`client.show(name)` の生 json、`recommended_for`)。
- `core/config.py:9-20`(`OllamaSettings` に `embedding_dim` 未存在 / `default_model` / `embedding_model`)、`core/config.py:92`(`qdrant_path = data_dir / "qdrant"`)。
- `apps/web/src/lib/api/types.ts:102-108`(`ModelInfo`、`kind` 未存在)。
- 統合テスト規約: `tests/integration/test_vector_store.py` の `@pytest.mark.qdrant` + `tmp_path` 作法、`pyproject.toml:95-97` の `qdrant` マーカー定義。

注意点(後続/レビュー向け):
- `kind` キーの導入は本来 Task 1(モデル分類)のスコープ。本タスクの `models.py` 実装は `classify_kind` の有無に依存しないローカルフォールバックを内蔵しているため単独で整合するが、Task 1 とのマージ時に `models.py` が二重定義にならないよう調整が必要(Task 1 側が `classify_kind` を `models_info.py` に置けば、本タスクの `_classify_kind` は自動でそれを使う)。
- Task 7(埋め込み切替 / 再インデックス)は `probe_embedding_dim`・`VectorStore.recreate_collection(dim)`・`collection_dim()` を Interfaces.Produces のシグネチャで利用する。

---

### Task 6: 埋め込みモデル参照を実行時 cfg 化(pipeline / retrieval / recording)

担当: 設計仕様「6. 横断方針 / 非機能 — embedding_model のサービス参照」。
目的: 再インデックス(Task 7)で `cfg.ollama.embedding_model` を変えたとき、プロセス再起動なしで `IngestionPipeline` / `RetrievalService` / `RecordingPipeline` が最新の埋め込みモデル名で `embed()` を呼ぶようにする。

**設計判断(実コードを Read した上での結論):**
現状3サービスは `deps`/コンストラクタに `embedding_model: str`(静的値)を受け、それを `embed(model=...)` に渡している(`core/ingestion/pipeline.py:93`, `core/retrieval/search.py:58`, `core/recording/recording_pipeline.py:288`)。最も侵襲が小さいのは **「省略可能な getter を1つ追加し、あれば実行時に呼ぶ。無ければ従来の静的値を使う」** 方式。理由:
- 既存の `embedding_model: str` フィールド/引数を **削除しない** ため、それを位置・キーワードで渡している既存テスト5本(`test_pipeline.py` / `test_search.py` / `test_recording_pipeline_fake.py` / `test_recording_pipeline_title.py` / `test_pipeline_compresses.py`)は無修正で通り続ける(`deps` に `config` 参照を持たせる案だと全テストの修正が必要で侵襲大)。
- `build_context` は getter(`lambda: config.ollama.embedding_model`)を渡すだけで、`config.ollama` を `model_copy(update=...)` で差し替えても closure が最新を読む。
- プロパティ化案は同等だが、3クラスへ `config` 全体を渡す結合を増やすため getter の方が疎。

各サービスに `_resolve_embedding_model() -> str` 内部ヘルパを設け、`embed` 呼び出し直前で解決する。

**Files:**
- Modify: `E:\00_Git\10_NotebookOllama\core\ingestion\pipeline.py`(`PipelineDeps`:27-33 / `embed` 呼び出し:93)
- Modify: `E:\00_Git\10_NotebookOllama\core\retrieval\search.py`(`RetrievalService.__init__`:34-46 / `embed` 呼び出し:58)
- Modify: `E:\00_Git\10_NotebookOllama\core\recording\recording_pipeline.py`(`RecordingPipelineDeps`:73-79 / `embed` 呼び出し:287-289)
- Modify: `E:\00_Git\10_NotebookOllama\apps\api\dependencies.py`(`build_context`:51-76)
- Test: `E:\00_Git\10_NotebookOllama\tests\integration\test_embedding_model_runtime.py`(Create, 新規)

**Interfaces:**

Consumes(先行タスクから / 既存): なし(本タスクは独立。`core.config.AppConfig.ollama.embedding_model: str`、`OllamaSettings` は frozen ではない通常 `BaseModel` であり、`build_context` は `config.ollama = config.ollama.model_copy(update={...})` で差し替え可能)。

Produces(Task 7 が前提にする契約):
- `PipelineDeps(..., embedding_model: str, embedding_model_getter: Callable[[], str] | None = None)` — getter があれば `run()` 内の各 `embed()` 呼び出しでそれを呼び最新モデル名を解決する。
- `RetrievalService(*, conn, vector_store, ollama, embedding_model: str, embedding_model_getter: Callable[[], str] | None = None)` — `search()` 内の `embed()` で実行時解決。
- `RecordingPipelineDeps(..., embedding_model: str, embedding_model_getter: Callable[[], str] | None = None)` — `run()` 内の `embed()` で実行時解決。
- `build_context(config)` は3サービスへ `embedding_model_getter=lambda: config.ollama.embedding_model` を配線する。よって Task 7 は `ctx.config.ollama = ctx.config.ollama.model_copy(update={"embedding_model": new_model})` を実行するだけで、再取り込み/再検索/録音取り込みが新モデルを使う。

---

- [ ] **Step 1: 失敗する統合テストを作成(3サービスが実行時 cfg を読むことを fake gateway で検証)**

新規ファイル `E:\00_Git\10_NotebookOllama\tests\integration\test_embedding_model_runtime.py` を作成する。`embed()` に渡された `model` 名を記録する fake gateway を使い、getter 経由で実行時に変更が反映されることを検証する(`build_context` 経由の結線も1ケースで確認)。

```python
"""embedding_model のサービス実行時参照テスト。

build_context で渡した getter が config.ollama.embedding_model の実行時変更を
反映し、再起動なしで pipeline / retrieval / recording_pipeline が新しい
埋め込みモデル名で embed() を呼ぶことを確認する。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from apps.api.dependencies import build_context
from core.config import AppConfig
from core.ingestion.pipeline import IngestionPipeline, PipelineDeps
from core.recording.recording_pipeline import RecordingPipeline, RecordingPipelineDeps
from core.retrieval.search import RetrievalService
from core.storage.chunks_repo import ChunkRecord, insert_chunks
from core.storage.database import connect, migrate
from core.storage.notebooks_repo import create_notebook
from core.storage.sources_repo import SourceStatus, create_source, get_source
from core.storage.vector_store import ChunkVector, VectorStore


class RecordingFakeGateway:
    """embed の model 名を記録。generate は校正/名前推定をスキップさせる無害な応答。"""

    def __init__(self) -> None:
        self.embed_models: list[str] = []

    async def embed(self, *, model: str, text: str) -> list[float]:
        self.embed_models.append(model)
        return [0.1, 0.2, 0.3, 0.4]

    async def generate(self, *, model, prompt, options=None) -> str:
        return ""


class FakeGateway:
    def __init__(self) -> None:
        self.embed_models: list[str] = []

    async def embed(self, *, model: str, text: str) -> list[float]:
        self.embed_models.append(model)
        return [1.0, 0.0, 0.0, 0.0]


class FakeVectorStore:
    def __init__(self) -> None:
        self.upserts: list = []

    def ensure_collection(self) -> None:
        pass

    def upsert(self, vectors) -> None:
        self.upserts.extend(list(vectors))


class FakeTranscriber:
    def transcribe(self, wav_path, *, channel, speaker_id, language="ja", session_id=""):
        from core.recording.transcriber import TranscriptSegment

        return [
            TranscriptSegment(
                id=None, session_id=session_id, channel="mic",
                start_ms=0, end_ms=1000, speaker_id=speaker_id,
                text="こんにちは", language="ja",
            )
        ]


class FakeDiarizer:
    def diarize(self, wav_path):
        return []


def _rec_conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    migrate(c)
    c.execute("INSERT INTO notebooks(id,name,created_at,updated_at) VALUES('nb','n','t','t')")
    c.execute(
        "INSERT INTO sources(id,notebook_id,kind,status,created_at,updated_at) "
        "VALUES('src','nb','recording','pending','t','t')"
    )
    return c


@pytest.mark.asyncio
async def test_retrieval_uses_getter_at_runtime(tmp_path):
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    src = create_source(conn, notebook_id=nb.id, kind="md", title="Doc", content_hash="h")
    insert_chunks(
        conn,
        [
            ChunkRecord(
                id="a" * 26, source_id=src.id, notebook_id=nb.id, ord=0,
                page=None, heading_path=None, text="hello", token_count=1,
            )
        ],
    )
    vs = VectorStore(path=tmp_path / "q", dim=4)
    vs.ensure_collection()
    vs.upsert(
        [
            ChunkVector(
                id="a" * 26, vector=[1, 0, 0, 0], notebook_id=nb.id,
                source_id=src.id, source_kind="md", page=None,
                heading_path=None, ord=0,
            )
        ]
    )
    gw = FakeGateway()
    current = {"model": "bge-m3"}
    svc = RetrievalService(
        conn=conn, vector_store=vs, ollama=gw,
        embedding_model="bge-m3",
        embedding_model_getter=lambda: current["model"],
    )
    await svc.search(notebook_id=nb.id, query="hi", limit=5)
    assert gw.embed_models[-1] == "bge-m3"
    # 実行時に cfg 相当を変更 → 再起動なしで反映される
    current["model"] = "nomic-embed-text"
    await svc.search(notebook_id=nb.id, query="hi", limit=5)
    assert gw.embed_models[-1] == "nomic-embed-text"


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_pipeline_uses_getter_at_runtime(tmp_path):
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    vs = VectorStore(path=tmp_path / "q", dim=4)
    vs.ensure_collection()
    gw = FakeGateway()
    current = {"model": "bge-m3"}
    pipeline = IngestionPipeline(
        deps=PipelineDeps(
            conn=conn, vector_store=vs, ollama=gw,
            embedding_model="bge-m3",
            embedding_model_getter=lambda: current["model"],
        )
    )
    src1 = create_source(conn, notebook_id=nb.id, kind="markdown", origin="a.md", content_hash="h1")
    await pipeline.run(source_id=src1.id, kind="markdown", data=b"# T\n\nbody one.\n")
    assert get_source(conn, src1.id).status == SourceStatus.READY
    assert gw.embed_models and all(m == "bge-m3" for m in gw.embed_models)

    current["model"] = "mxbai-embed-large"
    src2 = create_source(conn, notebook_id=nb.id, kind="markdown", origin="b.md", content_hash="h2")
    await pipeline.run(source_id=src2.id, kind="markdown", data=b"# T2\n\nbody two.\n")
    assert gw.embed_models[-1] == "mxbai-embed-large"


@pytest.mark.asyncio
async def test_recording_pipeline_uses_getter_at_runtime(tmp_path: Path):
    conn = _rec_conn()
    vs = FakeVectorStore()
    gw = RecordingFakeGateway()
    current = {"model": "bge-m3"}
    pipeline = RecordingPipeline(
        deps=RecordingPipelineDeps(
            conn=conn, vector_store=vs, ollama=gw,
            embedding_model="bge-m3",
            embedding_model_getter=lambda: current["model"],
            broker=None,
        )
    )
    current["model"] = "snowflake-arctic-embed"
    await pipeline.run(
        source_id="src", notebook_id="nb",
        mic_wav=tmp_path / "mic.wav", system_wav=None,
        transcriber=FakeTranscriber(), diarizer=FakeDiarizer(),
        model="qwen3", diarization_enabled=False, name_inference_enabled=False,
        name_threshold=0.7,
    )
    status = conn.execute("SELECT status FROM sources WHERE id='src'").fetchone()["status"]
    assert status == "ready"
    assert gw.embed_models, "embed が呼ばれていない"
    assert all(m == "snowflake-arctic-embed" for m in gw.embed_models)


def test_build_context_wires_embedding_getter(tmp_path):
    cfg = AppConfig(data_dir=tmp_path)
    cfg.ollama = cfg.ollama.model_copy(update={"embedding_model": "bge-m3"})
    ctx = build_context(cfg)
    # getter は build_context で配線され、cfg.ollama 差し替えを反映する
    assert ctx.pipeline._deps.embedding_model_getter is not None
    assert ctx.pipeline._deps.embedding_model_getter() == "bge-m3"
    assert ctx.recording_pipeline._deps.embedding_model_getter() == "bge-m3"
    ctx.config.ollama = ctx.config.ollama.model_copy(update={"embedding_model": "nomic-embed-text"})
    assert ctx.pipeline._deps.embedding_model_getter() == "nomic-embed-text"
    assert ctx.recording_pipeline._deps.embedding_model_getter() == "nomic-embed-text"
```

- [ ] **Step 2: 失敗を確認(まだ getter フィールドが無いので TypeError)**

Run: `uv run pytest tests/integration/test_embedding_model_runtime.py -v`
Expected: FAIL(`TypeError: ... got an unexpected keyword argument 'embedding_model_getter'`、および `test_build_context_wires_embedding_getter` は `AttributeError`)。qdrant マーカー付きの1本が環境により skip でも、他がエラーで落ちることを確認する。

- [ ] **Step 3: `IngestionPipeline` に getter を追加(最小実装)**

`E:\00_Git\10_NotebookOllama\core\ingestion\pipeline.py` の import に `Callable` を追加する。

```python
from typing import Any, Callable, Protocol
```

`PipelineDeps`(27-33行)へ getter フィールドを追加する。

```python
@dataclass
class PipelineDeps:
    conn: sqlite3.Connection
    vector_store: VectorStore
    ollama: _GatewayLike
    embedding_model: str
    broker: _BrokerLike | None = None
    embedding_model_getter: Callable[[], str] | None = None
```

`IngestionPipeline` に解決ヘルパを追加する(`__init__` 直後、37-38行のあと)。

```python
    def _embedding_model(self) -> str:
        getter = self._deps.embedding_model_getter
        return getter() if getter is not None else self._deps.embedding_model
```

`embed` 呼び出し(93行)を解決ヘルパ経由に変更する。

```python
                vec = await self._deps.ollama.embed(model=self._embedding_model(), text=rec.text)
```

- [ ] **Step 4: `RetrievalService` に getter を追加(最小実装)**

`E:\00_Git\10_NotebookOllama\core\retrieval\search.py` の import に `Callable` を追加する。

```python
from typing import Callable, Protocol
```

`RetrievalService.__init__`(34-46行)を getter 受け取りに変更する。

```python
    def __init__(
        self,
        *,
        conn: sqlite3.Connection,
        vector_store: VectorStore,
        ollama: _GatewayLike,
        embedding_model: str,
        embedding_model_getter: Callable[[], str] | None = None,
    ) -> None:
        self._conn = conn
        self._vs = vector_store
        self._ollama = ollama
        self._embedding_model = embedding_model
        self._embedding_model_getter = embedding_model_getter

    def _resolve_embedding_model(self) -> str:
        if self._embedding_model_getter is not None:
            return self._embedding_model_getter()
        return self._embedding_model
```

`search` 内の `embed` 呼び出し(58行)を解決ヘルパ経由に変更する。

```python
        qvec = await self._ollama.embed(model=self._resolve_embedding_model(), text=query)
```

- [ ] **Step 5: `RecordingPipeline` に getter を追加(最小実装)**

`E:\00_Git\10_NotebookOllama\core\recording\recording_pipeline.py` の import に `Callable` を追加する。

```python
from typing import Any, Callable, Protocol
```

`RecordingPipelineDeps`(73-79行)へ getter フィールドを追加する。

```python
@dataclass
class RecordingPipelineDeps:
    conn: sqlite3.Connection
    vector_store: _VectorStoreLike
    ollama: _GatewayLike
    embedding_model: str
    broker: _BrokerLike | None = None
    embedding_model_getter: Callable[[], str] | None = None
```

`RecordingPipeline` に解決ヘルパを追加する(`__init__` 直後、92-93行のあと)。

```python
    def _embedding_model(self) -> str:
        getter = self._deps.embedding_model_getter
        return getter() if getter is not None else self._deps.embedding_model
```

`embed` 呼び出し(287-289行)を解決ヘルパ経由に変更する。

```python
                vec = await self._deps.ollama.embed(
                    model=self._embedding_model(), text=chunk.text
                )
```

- [ ] **Step 6: `build_context` で getter を配線**

`E:\00_Git\10_NotebookOllama\apps\api\dependencies.py` の `build_context` で、3サービスへ `config.ollama.embedding_model` を読む closure を渡す。値渡しの `embedding_model=` は後方互換のため残す(初期値・fallback)。

`pipeline`(51-59行)を変更する。

```python
    pipeline = IngestionPipeline(
        deps=PipelineDeps(
            conn=conn,
            vector_store=vs,
            ollama=gateway,
            embedding_model=config.ollama.embedding_model,
            embedding_model_getter=lambda: config.ollama.embedding_model,
            broker=sse_broker,
        )
    )
```

`retrieval`(60-65行)を変更する。

```python
    retrieval = RetrievalService(
        conn=conn,
        vector_store=vs,
        ollama=gateway,
        embedding_model=config.ollama.embedding_model,
        embedding_model_getter=lambda: config.ollama.embedding_model,
    )
```

`recording_pipeline`(68-76行)を変更する。

```python
    recording_pipeline = RecordingPipeline(
        deps=RecordingPipelineDeps(
            conn=conn,
            vector_store=vs,
            ollama=gateway,
            embedding_model=config.ollama.embedding_model,
            embedding_model_getter=lambda: config.ollama.embedding_model,
            broker=sse_broker,
        )
    )
```

注: closure は `config` オブジェクトを束縛する。Task 7 が `ctx.config.ollama = ctx.config.ollama.model_copy(update={"embedding_model": ...})` で `config.ollama` を差し替えると、closure は最新の `config.ollama.embedding_model` を読むため再起動なしで反映される(`config` 変数自体は同一参照のまま)。

- [ ] **Step 7: 新規テストの成功を確認**

Run: `uv run pytest tests/integration/test_embedding_model_runtime.py -v`
Expected: PASS(qdrant 必須の `test_pipeline_uses_getter_at_runtime` はローカル qdrant 書込可なら PASS、不可環境では skip。他3本は PASS)。

- [ ] **Step 8: 既存テストを壊していないことを確認(値渡しを期待する既存5本を含む)**

`embedding_model` を静的値で渡している既存テスト群を回し、getter 追加が後方互換であることを確認する。

Run: `uv run pytest tests/integration/test_pipeline.py tests/integration/test_search.py tests/integration/test_recording_pipeline_fake.py tests/integration/test_recording_pipeline_title.py tests/integration/test_pipeline_compresses.py tests/integration/test_dependencies.py -v`
Expected: PASS(qdrant 必須ケースは環境により skip 可、FAIL は無いこと)。既存テストは `embedding_model_getter` を渡さないため fallback の静的値が使われ、挙動不変。**既存テストの修正は不要**(本方式は既存フィールドを保持するため)。

- [ ] **Step 9: フルスイートで回帰がないことを確認**

Run: `uv run pytest -q`
Expected: PASS(qdrant/ollama マーカーのスキップを除き、FAIL なし)。

- [ ] **Step 10: コミット**

Run:
```
git add core/ingestion/pipeline.py core/retrieval/search.py core/recording/recording_pipeline.py apps/api/dependencies.py tests/integration/test_embedding_model_runtime.py
git commit -m "feat(embedding): resolve embedding_model at runtime via cfg getter in pipeline/retrieval/recording"
```
Expected: コミット作成(Co-Authored-By trailer は付けない)。

---

補足(Task 7 への申し送り): 本タスクは「読み取り経路」のみを実行時 cfg 化した。Task 7 の再インデックスエンドポイントは (a) `ctx.config.ollama = ctx.config.ollama.model_copy(update={"embedding_model": model})` で in-memory 反映、(b) `VectorStore` の dim 更新/collection 再作成、(c) `save_section(...)` での永続化、を担う。本タスクの getter 配線により (a) 実行だけで3サービスが新モデルを使う(追加の再配線不要)。

---

### Task 7: 埋め込み切替=全チャンク再インデックス: `POST /api/settings/embedding/switch`

担当: 設計仕様 (C) バックエンド本体(最重量)。埋め込みモデルを切り替えると collection を新次元で再作成し、全ノートの全チャンクを再埋め込み(再 upsert)する。進捗を SSE で配信する。

**Files:**
- Modify: `apps/api/routers/settings.py`(`POST /api/settings/embedding/switch` + `GET /api/settings/events` を追加。後者は `events.py` の `stream_events` を雛形に `embedding_reindex` トピックを購読配信)
- Modify: `apps/api/schemas/settings.py`(`EmbeddingSwitchRequest` を追加)
- Modify(必要時): `core/storage/vector_store.py`(Task5 が `recreate_collection`/`collection_dim`/dim 更新を未実装なら最小追加。実装済みなら触らない。下記 Step 0 参照)
- Test: `tests/integration/test_api/test_embedding_switch_api.py`(新規)
- Reference(Read のみ): `apps/api/routers/events.py`(`stream_events` の SSE 作法)、`apps/api/sse.py`(`SseBroker.subscribe/publish/unsubscribe`)

**Interfaces:**

Consumes(先行タスクの正確なシグネチャ):
- Task1 `core.ollama.models_info.classify_kind(*, capabilities: list[str], name: str) -> str`(返り値 `"chat" | "embedding" | "both" | "unknown"`)。
- Task5 `async core.ollama.gateway.probe_embedding_dim(gateway: OllamaGateway, model: str) -> int`(短文を embed し `len(vector)` を返す。**`models_info` ではなく `gateway` に置かれる**ことに注意)。
- Task5 `core.storage.vector_store.VectorStore.recreate_collection(dim: int) -> None`(drop → `create_collection(size=dim)`、内部 `_dim` も `dim` に更新する)。
- Task5 `core.storage.vector_store.VectorStore.collection_dim() -> int | None`。
- Task6 横断方針: 各サービス(IngestionPipeline / RetrievalService / RecordingPipeline)が実行時に最新 `embedding_model` を読むよう `build_context` の結線を getter/cfg 参照へ変更済みであること。本タスクは `cfg.ollama` を `model_copy` で差し替えるため、Task6 が「実行時 `ctx.config.ollama.embedding_model` を読む」結線にしてあれば追加結線は不要。Task6 が未完了でも本タスク単体のテストは成立する(本タスクは collection と settings.json と SSE のみ検証する)。
- 既存: `OllamaClient.list_tags() -> list[dict]`(各 dict に `"name"`)、`OllamaClient.show(model) -> dict`(`"capabilities"` 配列を含みうる)。
- 既存: `OllamaGateway.embed(*, model: str, text: str) -> list[float]`。
- 既存: `notebooks_repo.list_notebooks(conn) -> list[NotebookRecord]`(`.id`)。
- 既存: `sources_repo.list_sources(conn, *, notebook_id: str) -> list[SourceRecord]`(`.id`, `.kind`)。
- 既存: `chunks_repo.list_chunks_for_source(conn, source_id) -> list[ChunkRecord]`(`.id`, `.notebook_id`, `.source_id`, `.ord`, `.page`, `.heading_path`, `.text`, `.start_ms`, `.end_ms`, `.speaker`。**`channel` は存在しない**ので `channel=None` 固定)。
- 既存: `VectorStore.upsert(vectors: Iterable[ChunkVector])`。`ChunkVector(id, vector, notebook_id, source_id, source_kind, page, heading_path, ord, start_ms=None, end_ms=None, speaker=None, channel=None)`。
- 既存: `core.settings_store.save_section(data_dir: Path, section: str, values: dict) -> None`。
- 既存: `SseBroker.publish(topic: str, payload: dict) -> None`(**async**。`await ctx.sse.publish(...)`)。
- 既存: AppError `ErrorCode.INPUT_INVALID` は HTTP 400 にマップ(`apps/api/main.py` status_map)。
- 既存 ctx 属性: `ctx.config`(=`cfg`)、`ctx.conn`、`ctx.vector_store`、`ctx.ollama`、`ctx.sse`。`cfg.data_dir: Path`、`cfg.ollama: OllamaSettings`(`embedding_model`, `default_model`)。

Produces(後続が依存する I/O 契約):
- `POST /api/settings/embedding/switch`、リクエスト body `{"model": str}`、成功時 200 + `{"model": str, "dim": int, "reindexed_chunks": int}`。
- 検証失敗(model が embedding/both でない or list_tags に存在しない)は 400 + AppError JSON(`{"error": {"code": "input.invalid", ...}}`)。
- **`GET /api/settings/events`**(Step 4b)— 再インデックス進捗の HTTP SSE 公開エンドポイント。`embedding_reindex` トピックを subscribe し `EventSourceResponse` で配信。Task 8 は `new EventSource('/api/settings/events')` で購読する。
- **内部 publish payload(`switch_embedding` → broker)** はトピック `"embedding_reindex"` に対し `type` を内包する:
  - `{"type": "reindex_progress", "done": int, "total": int}`
  - `{"type": "reindex_complete", "model": str, "dim": int}`
  - `{"type": "reindex_error", "message": str}`
- **HTTP SSE 配信契約(`GET /api/settings/events` の出力。Task 8 の `addEventListener` と一致)** — 配信 generator が `payload['type']` を SSE `event` 名へ写像し、`data` からは `type` を落とす:
  - `event: reindex_progress` / `data: {"done": int, "total": int}`
  - `event: reindex_complete` / `data: {"model": str, "dim": int}`
  - `event: reindex_error` / `data: {"message": str}`
  - すなわち Task 8 は **event 名 = `reindex_progress`/`reindex_complete`/`reindex_error`、data = `type` 抜き JSON** を受け取る。

---

- [ ] **Step 0: Task5 の VectorStore API を確認(コードは書かない)**
  `core/storage/vector_store.py` を Read し、`recreate_collection(dim: int)` と `collection_dim() -> int | None` が存在し、`recreate_collection` が内部 `self._dim` を `dim` に更新していることを確認する。
  - **存在し dim も更新している** → このステップは完了。Step 1 へ進む。
  - **存在しない / dim を更新していない** → 以下を `VectorStore` クラスへ最小追加してから進む(`from qdrant_client.http import models as qm` は import 済み)。
    ```python
        def collection_dim(self) -> int | None:
            try:
                info = self._client.get_collection(COLLECTION)
            except Exception:
                return None
            return info.config.params.vectors.size

        def recreate_collection(self, dim: int) -> None:
            existing = {c.name for c in self._client.get_collections().collections}
            if COLLECTION in existing:
                self._client.delete_collection(collection_name=COLLECTION)
            self._client.create_collection(
                collection_name=COLLECTION,
                vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
            )
            self._dim = dim
    ```
    追加した場合はこのファイルも以降の commit に含める。

- [ ] **Step 1: 失敗するテストを書く(リクエストスキーマ)**
  `apps/api/schemas/settings.py` の末尾に追加するスキーマを参照するテストファイルを新規作成する。まずファイルの冒頭〜fixture と「embedding-only でないモデルは 400」ケースを書く。`tests/integration/test_api/test_embedding_switch_api.py` を新規作成。
  ```python
  from __future__ import annotations

  import json

  import pytest
  from fastapi.testclient import TestClient

  from apps.api.main import create_app
  from core.storage import notebooks_repo, sources_repo
  from core.storage.chunks_repo import ChunkRecord, insert_chunks


  class _FakeGateway:
      """次元可変の fake 埋め込みゲートウェイ。embed 呼び出し回数を記録する。"""

      def __init__(self, dim: int) -> None:
          self.dim = dim
          self.embed_calls: list[tuple[str, str]] = []

      async def embed(self, *, model: str, text: str) -> list[float]:
          self.embed_calls.append((model, text))
          return [0.1] * self.dim


  def _seed_chunks(ctx, *, n: int) -> str:
      """1 ノート + 1 ソース + n チャンクを仕込み、source_id を返す。"""
      nb = notebooks_repo.create_notebook(ctx.conn, name="nb1")
      src = sources_repo.create_source(ctx.conn, notebook_id=nb.id, kind="pdf")
      chunks = [
          ChunkRecord(
              id=f"chunk-{i}",
              source_id=src.id,
              notebook_id=nb.id,
              ord=i,
              page=i,
              heading_path=f"H{i}",
              text=f"body {i}",
              token_count=3,
          )
          for i in range(n)
      ]
      insert_chunks(ctx.conn, chunks)
      ctx.conn.commit()
      return src.id


  def _mock_tags_show(client, *, name: str, capabilities: list[str]):
      """list_tags / show を respx でモックする helper を返す context manager。"""
      import httpx
      import respx

      mock = respx.mock(assert_all_called=False)
      mock.get("http://fake/api/tags").mock(
          return_value=httpx.Response(200, json={"models": [{"name": name}]})
      )
      mock.post("http://fake/api/show").mock(
          return_value=httpx.Response(200, json={"capabilities": capabilities})
      )
      return mock


  @pytest.fixture
  def client(tmp_path, monkeypatch):
      monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
      monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
      app = create_app()
      with TestClient(app) as c:
          yield c


  def test_switch_rejects_non_embedding_model(client):
      with _mock_tags_show(client, name="qwen2.5:14b", capabilities=["completion"]):
          r = client.post("/api/settings/embedding/switch", json={"model": "qwen2.5:14b"})
      assert r.status_code == 400
      assert r.json()["error"]["code"] == "input.invalid"
  ```
  - Run: `uv run pytest tests/integration/test_api/test_embedding_switch_api.py -v`
  - Expected: FAIL(エンドポイント未実装で 404、または import エラー)。

- [ ] **Step 2: 失敗を確認**
  - Run: `uv run pytest tests/integration/test_api/test_embedding_switch_api.py::test_switch_rejects_non_embedding_model -v`
  - Expected: FAIL(`assert 404 == 400` または route なし)。失敗内容が「endpoint 未実装」由来であることを確認する。

- [ ] **Step 3: リクエストスキーマを追加**
  `apps/api/schemas/settings.py` の末尾に追加する。
  ```python
  class EmbeddingSwitchRequest(BaseModel):
      model: str
  ```
  ファイル冒頭で `from pydantic import BaseModel` が import 済みであることを確認する(未 import ならテストが import エラーになる。既存 `OllamaSettingsSchema` 等が `BaseModel` 継承なので import 済みのはず)。

- [ ] **Step 4: エンドポイント本体を実装(検証 + 再インデックス + 永続化 + SSE)**
  `apps/api/routers/settings.py` の import 群と末尾に追加する。まず import を追加。
  ```python
  from apps.api.schemas.settings import (
      AppSettingsSchema,
      AudioSettingsSchema,
      EmbeddingSwitchRequest,
      GenerationSettingsSchema,
      OllamaSettingsSchema,
      RetrievalSettingsSchema,
  )
  from core.exceptions import AppError, ErrorCode
  from core.ollama.client import OllamaClient
  from core.ollama.gateway import probe_embedding_dim
  from core.ollama.models_info import classify_kind
  from core.settings_store import save_section
  from core.storage import chunks_repo, notebooks_repo, sources_repo
  from core.storage.vector_store import ChunkVector
  ```

  > 所在注記(Task5 と一致させること): `probe_embedding_dim` は **`core.ollama.gateway`** に実装される(Task5 Step 3)。`classify_kind` は **`core.ollama.models_info`**(Task1 Step 3)。両者は別モジュールなので import を 2 行に分ける。混在 import(`from core.ollama.models_info import classify_kind, probe_embedding_dim`)は ImportError となり settings ルータ読込=create_app が全損するため厳禁。
  (既存の `from apps.api.schemas.settings import (...)` ブロックを上記で置き換える。`EmbeddingSwitchRequest` を1行追加するだけ。他の import 行はファイル先頭の import 群に追記する。)
  続いて `get_stats` の後ろにエンドポイントを追加する。
  ```python
  _REINDEX_TOPIC = "embedding_reindex"


  @router.post("/settings/embedding/switch")
  async def switch_embedding(
      request: Request, body: EmbeddingSwitchRequest
  ) -> dict[str, Any]:
      ctx = request.app.state.ctx
      cfg = ctx.config
      model = body.model

      # 1. model が embedding|both であること検証(list_tags で存在確認 + classify_kind)
      client = OllamaClient(
          endpoint=cfg.ollama.endpoint,
          timeout=cfg.ollama.request_timeout_seconds,
      )
      tags = await client.list_tags()
      names = {t.get("name") for t in tags}
      if model not in names:
          raise AppError(ErrorCode.INPUT_INVALID, f"model {model} not installed")
      show = await client.show(model)
      kind = classify_kind(capabilities=show.get("capabilities", []) or [], name=model)
      if kind not in ("embedding", "both"):
          raise AppError(
              ErrorCode.INPUT_INVALID,
              f"model {model} is not an embedding model (kind={kind})",
          )

      try:
          # 2. 新次元を検出
          new_dim = await probe_embedding_dim(ctx.ollama, model)
          # 3. collection を新次元で再作成(内部 _dim も更新される)
          ctx.vector_store.recreate_collection(new_dim)

          # 4. 全ノートの全チャンクを走査し再埋め込み
          notebooks = notebooks_repo.list_notebooks(ctx.conn)
          all_chunks: list[tuple[str, ChunkRecord]] = []
          for nb in notebooks:
              for src in sources_repo.list_sources(ctx.conn, notebook_id=nb.id):
                  for ch in chunks_repo.list_chunks_for_source(ctx.conn, src.id):
                      all_chunks.append((src.kind, ch))
          total = len(all_chunks)

          done = 0
          await ctx.sse.publish(
              _REINDEX_TOPIC,
              {"type": "reindex_progress", "done": done, "total": total},
          )
          for source_kind, ch in all_chunks:
              vector = await ctx.ollama.embed(model=model, text=ch.text)
              ctx.vector_store.upsert(
                  [
                      ChunkVector(
                          id=ch.id,
                          vector=vector,
                          notebook_id=ch.notebook_id,
                          source_id=ch.source_id,
                          source_kind=source_kind,
                          page=ch.page,
                          heading_path=ch.heading_path,
                          ord=ch.ord,
                          start_ms=ch.start_ms,
                          end_ms=ch.end_ms,
                          speaker=ch.speaker,
                          channel=None,
                      )
                  ]
              )
              done += 1
              await ctx.sse.publish(
                  _REINDEX_TOPIC,
                  {"type": "reindex_progress", "done": done, "total": total},
              )

          # 5. in-memory 反映 + settings.json 永続化(default_model は現在値を保持)
          cfg.ollama = cfg.ollama.model_copy(update={"embedding_model": model})
          save_section(
              cfg.data_dir,
              "ollama",
              {
                  "default_model": cfg.ollama.default_model,
                  "embedding_model": model,
                  "embedding_dim": new_dim,
              },
          )

          # 6. 完了イベント
          await ctx.sse.publish(
              _REINDEX_TOPIC,
              {"type": "reindex_complete", "model": model, "dim": new_dim},
          )
      except AppError:
          raise
      except Exception as exc:
          await ctx.sse.publish(
              _REINDEX_TOPIC,
              {"type": "reindex_error", "message": str(exc)},
          )
          raise AppError(
              ErrorCode.OLLAMA_GENERATION_FAILED,
              "embedding reindex failed",
              detail=str(exc),
          ) from exc

      return {"model": model, "dim": new_dim, "reindexed_chunks": total}
  ```
  注: `Any` は既存 import(`from typing import Any`)で利用可。検証由来の `AppError(INPUT_INVALID)` は `try` の外で raise しているため 400 のまま伝播する(SSE error は出さない)。

- [ ] **Step 4b: 再インデックス進捗 SSE の購読エンドポイント `GET /api/settings/events` を実装する**

  `switch_embedding` は `ctx.sse.publish(_REINDEX_TOPIC, ...)` で broker に流すだけで、HTTP で SSE を公開する経路が無い。既存の HTTP SSE 公開は `apps/api/routers/events.py` の `GET /api/notebooks/{id}/events` のみで、これはノート単位 `topic=f"notebook:{id}"` ・固定 event 名 `source_status` ・data=全 payload を流す方式(Read 済み)。再インデックスはノート横断のためこれを流用できない。Task 8 は `new EventSource('/api/settings/events')` で購読し、`addEventListener('reindex_progress'|'reindex_complete'|'reindex_error', ...)`(= **SSE の event 名**)で待ち、各 `data`(JSON、`type` 抜き)を `JSON.parse` する。よって本エンドポイントは「**`payload['type']` を SSE event 名へ写像し、`data` からは `type` を落とす**」契約に固定する。

  `apps/api/routers/settings.py` に、`events.py` の `stream_events` を雛形に以下を追加する。まず import を追加する(`apps/api/routers/events.py` と同じ顔ぶれ。`asyncio`/`json` は本ファイルで未 import なら追加、`EventSourceResponse` も追加する)。Step 4 で追記した import 群に続けて、ファイル先頭側へ次を加える:
  ```python
  import asyncio
  import json
  from collections.abc import AsyncIterator

  from sse_starlette.sse import EventSourceResponse
  ```
  (`from fastapi import APIRouter, Request` は既存。`json` / `asyncio` がファイル冒頭に無ければ追加。`Any` は既存 import。)

  続いて、Step 4 で追加した `_REINDEX_TOPIC = "embedding_reindex"` の定義を再利用し、`switch_embedding` の**直後**に購読エンドポイントを追加する:
  ```python
  @router.get("/settings/events")
  async def settings_events(request: Request) -> EventSourceResponse:
      ctx = request.app.state.ctx
      queue = ctx.sse.subscribe(_REINDEX_TOPIC)

      async def gen() -> AsyncIterator[dict]:
          try:
              while True:
                  if await request.is_disconnected():
                      return
                  try:
                      payload = await asyncio.wait_for(queue.get(), timeout=15)
                      # payload['type'] を SSE event 名へ写像し、data からは type を落とす。
                      # 例: {"type":"reindex_progress","done":1,"total":3}
                      #   -> event: reindex_progress / data: {"done":1,"total":3}
                      event = payload.get("type", "message")
                      data = {k: v for k, v in payload.items() if k != "type"}
                      yield {
                          "event": event,
                          "data": json.dumps(data, ensure_ascii=False),
                      }
                  except TimeoutError:
                      yield {"event": "ping", "data": ""}
          finally:
              ctx.sse.unsubscribe(_REINDEX_TOPIC, queue)

      return EventSourceResponse(gen())
  ```

  > 契約の確定(Task 8 と一致):
  > - 購読 URL = `GET /api/settings/events`(プレフィックス `/api` は `router = APIRouter(prefix="/api", ...)` 由来。`@router.get("/settings/events")` で実 URL は `/api/settings/events`)。
  > - SSE `event` 名 = `payload['type']` の値、すなわち `reindex_progress` / `reindex_complete` / `reindex_error`。
  > - SSE `data`(JSON)= `payload` から `type` を除いた残り。`reindex_progress`→`{"done":int,"total":int}` / `reindex_complete`→`{"model":str,"dim":int}` / `reindex_error`→`{"message":str}`。
  > - `SseBroker.subscribe(topic)` は同期で `asyncio.Queue` を返し、`unsubscribe(topic, queue)` で解除、`publish(topic, payload)` は async(`apps/api/sse.py` で Read 済み)。`finally` で必ず unsubscribe する。ping は 15 秒 timeout で送出(`events.py` と同作法)。

- [ ] **Step 5: 拒否ケースの成功を確認**
  - Run: `uv run pytest tests/integration/test_api/test_embedding_switch_api.py::test_switch_rejects_non_embedding_model -v`
  - Expected: PASS。

- [ ] **Step 6: 成功パス(再作成 + 全 upsert + 永続化)の失敗テストを追加**
  `tests/integration/test_api/test_embedding_switch_api.py` の末尾に追加する。`ctx.ollama` を fake(次元 8)に差し替え、`ctx.vector_store` は実物のまま collection の次元が変わることを検証する。`probe_embedding_dim` は内部で `ctx.ollama.embed` を呼ぶ実装(Task5)のため fake で次元 8 が返る。
  ```python
  def test_switch_recreates_collection_and_reindexes_all_chunks(client, tmp_path):
      ctx = client.app.state.ctx
      src_id = _seed_chunks(ctx, n=3)

      fake = _FakeGateway(dim=8)
      ctx.ollama = fake

      with _mock_tags_show(client, name="bge-m3", capabilities=["embedding"]):
          r = client.post("/api/settings/embedding/switch", json={"model": "bge-m3"})
      assert r.status_code == 200, r.text
      body = r.json()
      assert body["model"] == "bge-m3"
      assert body["dim"] == 8
      assert body["reindexed_chunks"] == 3

      # collection が新次元 8 で再作成されている
      assert ctx.vector_store.collection_dim() == 8

      # 全チャンク(3) が再 embed された(+ probe 用の短文 embed 1 回)
      reindex_calls = [c for c in fake.embed_calls if c[1].startswith("body ")]
      assert len(reindex_calls) == 3
      assert all(c[0] == "bge-m3" for c in reindex_calls)

      # 検索で再 upsert されたベクトルが新次元で引けること
      hits = ctx.vector_store.search(
          query=[0.1] * 8, notebook_id=ctx.conn.execute(
              "SELECT notebook_id FROM sources WHERE id=?", (src_id,)
          ).fetchone()[0], limit=10
      )
      assert len(hits) == 3

      # settings.json に embedding_model / embedding_dim / default_model が保存されている
      sj = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
      assert sj["ollama"]["embedding_model"] == "bge-m3"
      assert sj["ollama"]["embedding_dim"] == 8
      assert "default_model" in sj["ollama"]
  ```

- [ ] **Step 7: 失敗を確認**
  - Run: `uv run pytest tests/integration/test_api/test_embedding_switch_api.py::test_switch_recreates_collection_and_reindexes_all_chunks -v`
  - Expected: PASS が想定だが、もし FAIL する場合は原因を切り分ける。Task5(`probe_embedding_dim`/`recreate_collection`/`collection_dim`)が未実装なら ImportError/AttributeError になる。その場合は Step 0 を再確認し Task5 の完了を待つ。Task5 完了済みなら PASS するはず。

- [ ] **Step 8: 進捗イベント発火の失敗テストを追加**
  SSE トピック `"embedding_reindex"` を subscribe して `reindex_progress`(初回 done=0/total=3 と最終 done=3)・`reindex_complete` が流れることを検証する。`SseBroker.publish` は async・`subscribe(topic)` は同期で `asyncio.Queue` を返すため、TestClient のループ内で取り出す。`client.portal` 経由でなく、エンドポイント実行と同一イベントループ上で queue が満たされるため、テストはエンドポイント呼出し前に subscribe しておく必要がある。anyio の portal を使って subscribe → POST → drain する。
  ```python
  def test_switch_publishes_progress_events(client):
      ctx = client.app.state.ctx
      _seed_chunks(ctx, n=2)
      ctx.ollama = _FakeGateway(dim=8)

      portal = client.portal  # anyio BlockingPortal (TestClient コンテキスト内)
      queue = portal.call(ctx.sse.subscribe, "embedding_reindex")

      with _mock_tags_show(client, name="bge-m3", capabilities=["embedding"]):
          r = client.post("/api/settings/embedding/switch", json={"model": "bge-m3"})
      assert r.status_code == 200

      events: list[dict] = []
      while not queue.empty():
          events.append(queue.get_nowait())

      types = [e["type"] for e in events]
      assert "reindex_progress" in types
      assert "reindex_complete" in types
      # 最初の progress は done=0、最後の progress は done=total=2
      progress = [e for e in events if e["type"] == "reindex_progress"]
      assert progress[0]["done"] == 0
      assert progress[0]["total"] == 2
      assert progress[-1]["done"] == 2
      complete = [e for e in events if e["type"] == "reindex_complete"][0]
      assert complete["model"] == "bge-m3"
      assert complete["dim"] == 8
  ```
  注: `client.portal` が利用できない場合(TestClient バージョン差)は、代替として `client._portal` または `with create_app()` の lifespan 内で `anyio.from_thread` を使う。まず `client.portal` で実行し、`AttributeError` が出たら `portal = client._portal` に変える。

- [ ] **Step 9: 進捗テストの成功を確認**
  - Run: `uv run pytest tests/integration/test_api/test_embedding_switch_api.py::test_switch_publishes_progress_events -v`
  - Expected: PASS。`client.portal` が AttributeError の場合は Step 8 注記に従い `client._portal` へ修正し再実行。

- [ ] **Step 9b: `GET /api/settings/events` の SSE 配信契約(event 名写像 / data の type 抜き)をテストする**
  購読エンドポイントが `payload['type']` を SSE `event` 名へ写像し、`data` から `type` を落とすことを TestClient の SSE ストリームで確認する。topic 名 `"embedding_reindex"` の配信側・購読側一致もこのテストで担保する(switch の publish → GET /events で受信)。`tests/integration/test_api/test_embedding_switch_api.py` の末尾に追記する。

  `httpx`(TestClient 経由)で `stream=True` 相当の生テキストを読む。`EventSourceResponse` は `event: <name>\ndata: <json>\n\n` 形式で出力するため、最初の `reindex_complete` を待って 1 件パースする。switch を別スレッド(anyio portal)で起動し、その間 GET ストリームを読む形にする。
  ```python
  def test_settings_events_maps_type_to_event_name(client):
      ctx = client.app.state.ctx
      _seed_chunks(ctx, n=1)
      ctx.ollama = _FakeGateway(dim=8)

      # GET /api/settings/events を開いたまま、別スレッドで switch を発火させる。
      portal = client.portal

      def _fire():
          with _mock_tags_show(client, name="bge-m3", capabilities=["embedding"]):
              return client.post(
                  "/api/settings/embedding/switch", json={"model": "bge-m3"}
              )

      seen_events: list[str] = []
      seen_complete: dict | None = None
      with client.stream("GET", "/api/settings/events") as stream:
          fut = portal.start_task_soon(
              lambda: __import__("anyio").to_thread.run_sync(_fire)
          )
          event_name = None
          for line in stream.iter_lines():
              if line.startswith("event:"):
                  event_name = line.split(":", 1)[1].strip()
                  seen_events.append(event_name)
              elif line.startswith("data:") and event_name == "reindex_complete":
                  seen_complete = json.loads(line.split(":", 1)[1].strip())
                  break
          fut.result()

      # event 名は payload['type'] の写像(reindex_progress/complete)であること
      assert "reindex_progress" in seen_events
      assert "reindex_complete" in seen_events
      # data からは type が落ちている(complete は model/dim のみ)
      assert seen_complete == {"model": "bge-m3", "dim": 8}
  ```
  - Run: `uv run pytest tests/integration/test_api/test_embedding_switch_api.py::test_settings_events_maps_type_to_event_name -v`
  - Expected: PASS。`client.portal` / `start_task_soon` が TestClient バージョン差で使えない場合は、最小限「`GET /api/settings/events` が 200 を返し、SSE 1 行目が `event: ping`(または初回 timeout 前なら接続維持)であること」だけを確認する縮退テストに落とし、topic 名 `"embedding_reindex"` の一致は Step 8 の broker 直購読テストで担保する(どちらかで topic 一致が担保されればよい)。

- [ ] **Step 10: ファイル全体・回帰確認**
  - Run: `uv run pytest tests/integration/test_api/test_embedding_switch_api.py tests/integration/test_settings_audio.py tests/integration/test_api/test_models_api.py -v`
  - Expected: 全 PASS(新規3ケース + 既存 settings/audio・models が壊れていないこと)。

- [ ] **Step 11: commit**
  - Run:
    ```bash
    git add apps/api/routers/settings.py apps/api/schemas/settings.py tests/integration/test_api/test_embedding_switch_api.py core/storage/vector_store.py
    git commit -m "feat(settings): add POST /api/settings/embedding/switch with full reindex and SSE progress"
    ```
  - 注: Step 0 で `core/storage/vector_store.py` を変更していない場合は `git add` から除外する。
  - Expected: コミット成功(Co-Authored-By trailer は付けない)。

---

補足(実装者向け注意):
- `channel` は `ChunkRecord` に存在しないため `ChunkVector(..., channel=None)` 固定。`speaker`/`start_ms`/`end_ms` は `ChunkRecord` のフィールドをそのまま渡す(録音由来でなければ `None`)。
- `source_kind` は `ChunkRecord` にないため、走査時に親 `SourceRecord.kind` を保持して渡す(上記 `all_chunks: list[tuple[str, ChunkRecord]]`)。
- `SseBroker.publish` は **async**。必ず `await ctx.sse.publish(...)`。`subscribe` は同期で `asyncio.Queue` を返す。
- 検証 400(`INPUT_INVALID`)は `try` ブロックの外で raise しており、`main.py` の status_map で 400 になる。再インデックス中の例外は `reindex_error` を publish したうえで `OLLAMA_GENERATION_FAILED`(500)として表面化する(MVP 方針=エラー表面化 + 再実行可能、自動ロールバックなし)。
- Task6 が「サービスが実行時に `cfg.ollama.embedding_model` を読む」結線を済ませていれば、本エンドポイントの `cfg.ollama = cfg.ollama.model_copy(...)` だけで以降の取り込み/検索が新モデルを使う。Task6 未完了でも本タスクのテストは独立して PASS する。
- 関連ファイル(実装者が開く):
  - `E:\00_Git\10_NotebookOllama\apps\api\routers\settings.py`
  - `E:\00_Git\10_NotebookOllama\apps\api\schemas\settings.py`
  - `E:\00_Git\10_NotebookOllama\core\storage\vector_store.py`
  - `E:\00_Git\10_NotebookOllama\core\ollama\models_info.py`(Task1/Task5 の追加先)
  - `E:\00_Git\10_NotebookOllama\tests\integration\test_api\test_embedding_switch_api.py`(新規)

---

### Task 8: 設定UI: 埋め込みモデル <select> + 次元警告バナー + 再インデックス進捗(SSE)

**Files:**
- Modify: `apps/web/src/lib/api/types.ts`(`ModelInfo` に `kind`/`embedding_dim` を消費宣言、`OllamaSettings` に `embedding_dim` を追加、再インデックス用イベント型を追加)
- Modify: `apps/web/src/lib/api/settings.ts`(`switchEmbedding(model)` 追加)
- Create: `apps/web/src/lib/api/reindexEvents.ts`(再インデックス専用 EventSource ヘルパ)
- Modify: `apps/web/src/routes/settings/+page.svelte`(`section==='models'` を `<select>`+警告+進捗 UI 化)
- Test: `apps/web/` の型チェック/ビルド(`npm run check` / `npm run build`)。視覚検証は末尾 Step の Playwright ゲート(実機スクショ必須)。

**Interfaces:**

Consumes(先行タスクが必ずこのシグネチャで提供していること。実装前に各先行タスクの成果を Read し差異があれば合わせる):
- Task1: `ModelInfo.kind: "chat" | "embedding" | "both" | "unknown"`(`/api/models` の各 model に付与済み)。
- Task5: `ModelInfo.embedding_dim: number | null`(embedding/both のモデルにプローブ結果。失敗時 `null`)。`/api/models` 由来。
- Task7: `POST /api/settings/embedding/switch`(body `{ model: string }`)。chat-only モデルは HTTP 400(`INPUT_INVALID`)。即時レスポンスは小さな JSON(本タスクは中身に依存しない)、進捗は SSE で配信。
- Task7: 再インデックス SSE。トピック購読 URL = `GET /api/settings/events`(Task7 Step 4b で実装)。SSE `event:` 名 = `payload['type']` の写像、`data:`(JSON)は `type` を落とした残り(Task7 配信 generator が固定する契約):
  - `event: reindex_progress` → `data: { "done": number, "total": number }`
  - `event: reindex_complete` → `data: { "model": string, "dim": number }`
  - `event: reindex_error` → `data: { "message": string }`
  - この URL・event 名・data 構造は Task7 Produces と一致済み。`reindexEvents.ts` の `addEventListener` 名と `EventSource` URL はこの契約どおりに書く(齟齬が出た場合のみこの 1 ファイルで吸収)。
- Task5: `/api/settings` の `OllamaSettings` に `embedding_dim: number | null` が追加され、現行 collection 次元(`ctx.vector_store.collection_dim()`)として返る(本タスクの「現行次元」`curDim` 取得元)。**この露出は Task 5 Step 13b の責務**(Task 7 ではない)。

Produces(後続が依存しうるもの):
- `settingsApi.switchEmbedding(model: string): Promise<unknown>`(`api/settings.ts`)。
- `openReindexEvents(handlers): () => void`(`api/reindexEvents.ts`)。型は下記 Step1 で定義。
- 型: `OllamaSettings.embedding_dim`、`ModelInfo.kind`/`ModelInfo.embedding_dim`、`ReindexProgress`/`ReindexComplete`/`ReindexError`(`api/types.ts`)。

---

- [ ] **Step 1: 型を追加(`OllamaSettings.embedding_dim`、再インデックスイベント型)。`ModelInfo` は部分編集**
  本タスクは Task 1(`ModelInfo.kind` 追加)・Task 5(`ModelInfo.embedding_dim?: number | null` 追加)適用後の `apps/web/src/lib/api/types.ts` を**部分編集**する。`ModelInfo` を全置換しない(Task 1/5 の追加と齟齬を起こす)。

  **Edit 1-1(`ModelInfo.embedding_dim` を必須化。Task 5 が optional で入れている)**: Task 8 は `selectedEmbedding.embedding_dim` を必ず参照するため optional の `?` を外して必須にする。`old_string`(Task 1/5 適用後に存在する形):
```ts
  kind: "chat" | "embedding" | "both" | "unknown";
  recommended_for: string[];
  embedding_dim?: number | null;
}
```
  `new_string`:
```ts
  kind: "chat" | "embedding" | "both" | "unknown";
  recommended_for: string[];
  embedding_dim: number | null;
}
```
  > 注: Task 1 が `kind` を、Task 5 が `embedding_dim?` を `ModelInfo` に追加済みの前提。フィールド順は Task 1/5 の実体に依存するため、`old_string` が一致しなければ実体の並びに合わせて `embedding_dim?` 行だけを `embedding_dim`(`?` 抜き)へ置換する 1 行 Edit に縮約してよい。`kind` は再宣言しない。

  **Edit 1-2(フロント `OllamaSettings` に `embedding_dim` を追加)**: バックエンドは Task 5 Step 13b が `GET /api/settings.ollama.embedding_dim` を返すので、フロント型にも足す。`old_string`(現状 line 121-125):
```ts
export interface OllamaSettings {
  endpoint: string;
  default_model: string;
  embedding_model: string;
}
```
  `new_string`:
```ts
export interface OllamaSettings {
  endpoint: string;
  default_model: string;
  embedding_model: string;
  embedding_dim: number | null;
}
```

  **Edit 1-3(再インデックス SSE のペイロード型を追加)**: 同ファイル末尾(`RetrievalHit` の後)に追記する。
```ts
export interface ReindexProgress {
  done: number;
  total: number;
}

export interface ReindexComplete {
  model: string;
  dim: number;
}

export interface ReindexError {
  message: string;
}
```

- [ ] **Step 2: 型チェックで現状を確認**
  Run: `cd apps/web && npm run check`
  Expected: この時点では `OllamaSettings.embedding_dim` 必須化により、`OllamaSettings` を構築/モックする箇所(あれば)で型不足エラーが出るか、または `ModelInfo.embedding_dim` の `?` 除去で optional 前提の参照があれば型差が出る。エラーが「本 Step で追加/変更した型起因」であることを目視確認する(無関係な既存エラーがないこと)。`kind`/`embedding_dim` 自体は Task 1/5 で既に `ModelInfo` に入っているため、それらの「未定義」エラーが出る場合は Task 1/5 未完了(実行順違反)なので先行タスクの完了を確認する(推測で握りつぶさない)。後続 Step で `<select>`/警告/進捗 UI を追加すると `embedding_dim`/`switchEmbedding`/`openReindexEvents` の参照が解決し、Step 8 で 0 errors になる。

- [ ] **Step 3: `switchEmbedding` を settings API に追加(部分編集。Task 3 の `putOllama` を保持)**
  本タスクは Task 3 適用後の `apps/web/src/lib/api/settings.ts` に対し**部分編集**する。Task 3 が既に `putOllama`(と import の `OllamaSettings`/`OllamaSettingsUpdate`)を追加済みなので、それを**消さず** `switchEmbedding` を 1 メソッド追記するだけにする。全置換禁止。

  Edit: `putOllama` メソッドの閉じ `}),` の直後に `switchEmbedding` を挿入する。`old_string`(Task 3 適用後に存在する形):
```ts
  putOllama: (body: OllamaSettingsUpdate) =>
    request<OllamaSettings>('/api/settings/ollama', {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
};
```
  `new_string`:
```ts
  putOllama: (body: OllamaSettingsUpdate) =>
    request<OllamaSettings>('/api/settings/ollama', {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  switchEmbedding: (model: string) =>
    request<unknown>('/api/settings/embedding/switch', {
      method: 'POST',
      body: JSON.stringify({ model }),
    }),
};
```

  > 注: `import` 行は Task 3 が `OllamaSettings`/`OllamaSettingsUpdate` を追加済みのため**変更不要**。`switchEmbedding` は追加 import を要さない(`request<unknown>` のみ)。もし Task 3 未適用で `putOllama` が存在しなければ実行順違反(Global Constraints の「Task 3 → Task 8」)なので、先に Task 3 を適用すること。

- [ ] **Step 4: 再インデックス SSE ヘルパを新規作成(最小実装)**
  Create `apps/web/src/lib/api/reindexEvents.ts`。既存 `api/events.ts` の `EventSource` + 名前付き `addEventListener` + クローザ返却パターンに合わせる。グローバル(ノート非依存)トピック `GET /api/settings/events` を購読する。

```ts
import type { ReindexProgress, ReindexComplete, ReindexError } from './types';

export interface ReindexHandlers {
  onProgress?: (ev: ReindexProgress) => void;
  onComplete?: (ev: ReindexComplete) => void;
  onError?: (ev: ReindexError) => void;
}

/**
 * 設定レベルの SSE(再インデックス進捗)を購読する。
 * Task7 が `GET /api/settings/events` に `reindex_progress` /
 * `reindex_complete` / `reindex_error` を配信する前提。
 * URL・イベント名が Task7 実装と異なる場合はこのファイルのみ修正する。
 * 戻り値を呼ぶと購読を閉じる。
 */
export function openReindexEvents(handlers: ReindexHandlers): () => void {
  const es = new EventSource('/api/settings/events');

  es.addEventListener('reindex_progress', (e) => {
    try {
      handlers.onProgress?.(JSON.parse((e as MessageEvent).data) as ReindexProgress);
    } catch {
      // ignore malformed payload
    }
  });
  es.addEventListener('reindex_complete', (e) => {
    try {
      handlers.onComplete?.(JSON.parse((e as MessageEvent).data) as ReindexComplete);
    } catch {
      // ignore
    }
  });
  es.addEventListener('reindex_error', (e) => {
    try {
      handlers.onError?.(JSON.parse((e as MessageEvent).data) as ReindexError);
    } catch {
      // ignore
    }
  });

  return () => es.close();
}
```

- [ ] **Step 5: `<script>` に埋め込み切替の state/ロジックを追記(部分編集。Task 3 の追加を保持)**
  本タスクは Task 3 適用後の `apps/web/src/routes/settings/+page.svelte` に対し**部分編集**する。Task 3 は既に (a) `import { pushToast } from '$lib/components/Toast.svelte';` を追加し、(b) `goBack()` の後に `chatModelNames()` / `onDefaultModelChange()` を追記し、(c) 既定モデル(LLM)の `<dd>` を `<select>` 化済みである。**これらを消さない**。`<script>` の全置換は禁止(Task 3 の (B-1) が消える)。以下の 3 つの Edit で必要な import / state / handler だけを追記する。

  **Edit 5-1(import の追記)**: svelte の `onMount` import に `onDestroy` を足し、埋め込み用 import を追加する。`settingsStore`/`modelsStore`/`pushToast`(Task 3 が追加済み)は**再 import しない**。`old_string`(Task 3 適用後の冒頭。`pushToast` 行は Task 3 が追加済み):
```svelte
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { ArrowLeft } from '@lucide/svelte';
  import { navMemoryStore } from '$lib/stores/navMemory.svelte';
  import { settingsStore } from '$lib/stores/settings.svelte';
  import { modelsStore } from '$lib/stores/models.svelte';
  import { formatBytes } from '$lib/utils/format';
  import Spinner from '$lib/components/Spinner.svelte';
  import AudioSettingsSection from '$lib/components/settings/AudioSettingsSection.svelte';
  import { pushToast } from '$lib/components/Toast.svelte';
```
  `new_string`:
```svelte
  import { onMount, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { ArrowLeft } from '@lucide/svelte';
  import { navMemoryStore } from '$lib/stores/navMemory.svelte';
  import { settingsStore } from '$lib/stores/settings.svelte';
  import { modelsStore } from '$lib/stores/models.svelte';
  import { formatBytes } from '$lib/utils/format';
  import { settingsApi } from '$lib/api/settings';
  import { openReindexEvents } from '$lib/api/reindexEvents';
  import Spinner from '$lib/components/Spinner.svelte';
  import AudioSettingsSection from '$lib/components/settings/AudioSettingsSection.svelte';
  import { pushToast } from '$lib/components/Toast.svelte';
  import type { ModelInfo } from '$lib/api/types';
```
  > 注: `pushToast` は Task 3 が `AudioSettingsSection` import 行の直後に追加している。上の `old_string` はその Task 3 適用後の並びを前提にしている。実ファイルで `pushToast` 行の位置が異なる場合は、`onMount`→`onMount, onDestroy` の 1 行だけを置換し、`settingsApi`/`openReindexEvents`/`ModelInfo` import は `AudioSettingsSection` import 行の直後に別 Edit で挿入してよい(import の重複だけ避ける)。

  **Edit 5-2(state/derived の追加)**: `section` の `$state` 宣言の直後に埋め込み state と派生値を挿入する。`old_string`:
```svelte
  let section = $state<'models' | 'gen' | 'audio' | 'storage' | 'modelsList'>('audio');
```
  `new_string`:
```svelte
  let section = $state<'models' | 'gen' | 'audio' | 'storage' | 'modelsList'>('audio');

  // --- 埋め込みモデル切替 (section==='models') の state ---
  // <select> の選択値。'' = 未選択(=現行と同じ。切替なし)。
  // finding 15: <option value={null}> は HTML で文字列化してぶれるため、Task 3/4 と
  // 統一して value="" を「現行/未選択」に割り当て、'' を切替なしとして正規化する。
  let pendingEmbedding = $state('');
  // 再インデックス進行状況。null = 走っていない。
  let reindex = $state<{ done: number; total: number } | null>(null);
  let switching = $state(false);
  let closeReindex: (() => void) | null = null;

  // 現行の埋め込みモデル名・次元(settings 由来)。
  const curEmbeddingModel = $derived(settingsStore.settings?.ollama.embedding_model ?? null);
  const curDim = $derived(settingsStore.settings?.ollama.embedding_dim ?? null);

  // 埋め込み用途に使えるモデル(kind が embedding | both)。
  const embeddingModels = $derived(
    modelsStore.models.filter((m) => m.kind === 'embedding' || m.kind === 'both'),
  );

  // 切替対象。'' (未選択) または現行と同じなら null(警告/ボタンを出さない)。
  const switchTarget = $derived(
    pendingEmbedding !== '' && pendingEmbedding !== curEmbeddingModel
      ? pendingEmbedding
      : null,
  );

  // 選択中(= switchTarget、未選択なら現行)のモデル情報。
  const selectedEmbedding = $derived<ModelInfo | null>(
    embeddingModels.find((m) => m.name === (switchTarget ?? curEmbeddingModel)) ?? null,
  );

  // 警告判定。
  // - 次元が現行と異なる → dim 警告。
  // - 次元は同じだが別モデル → 「再インデックス推奨」注記。
  const newDim = $derived(selectedEmbedding?.embedding_dim ?? null);
  const dimWarning = $derived(
    switchTarget !== null && newDim !== null && curDim !== null && newDim !== curDim,
  );
  const sameDimNotice = $derived(switchTarget !== null && !dimWarning);
```

  **Edit 5-3(`onDestroy` + `confirmSwitch` ハンドラの追加)**: Task 3 が追記した `onDefaultModelChange` 関数の閉じ `}` の直後(= `</script>` の直前)に、`onDestroy` 登録と `confirmSwitch` を追記する。`onMount` は Task 3/既存のものをそのまま使う(再宣言しない)。`old_string`(Task 3 が `onDefaultModelChange` を追記した末尾。Task 3 の実体に合わせる。下は Task 3 Step 7 の末尾形):
```svelte
  async function onDefaultModelChange(e: Event) {
    const select = e.currentTarget as HTMLSelectElement;
    const next = select.value;
    const prev = settingsStore.settings?.ollama.default_model ?? '';
    if (next === prev) return;
    try {
      await settingsStore.putOllama(next);
      pushToast(`既定モデルを ${next} に変更しました`, 'success');
    } catch (err) {
      select.value = prev; // 失敗時は選択を元に戻す
      const msg = err instanceof Error ? err.message : String(err);
      pushToast(`既定モデルの変更に失敗しました: ${msg}`, 'error');
    }
  }
</script>
```
  `new_string`:
```svelte
  async function onDefaultModelChange(e: Event) {
    const select = e.currentTarget as HTMLSelectElement;
    const next = select.value;
    const prev = settingsStore.settings?.ollama.default_model ?? '';
    if (next === prev) return;
    try {
      await settingsStore.putOllama(next);
      pushToast(`既定モデルを ${next} に変更しました`, 'success');
    } catch (err) {
      select.value = prev; // 失敗時は選択を元に戻す
      const msg = err instanceof Error ? err.message : String(err);
      pushToast(`既定モデルの変更に失敗しました: ${msg}`, 'error');
    }
  }

  onDestroy(() => {
    closeReindex?.();
  });

  async function confirmSwitch() {
    if (!switchTarget) return;
    const target = switchTarget;
    const ok = window.confirm(
      `埋め込みモデルを「${target}」に切り替えます。全ソースを再インデックスします(数分かかる場合があります)。続行しますか?`,
    );
    if (!ok) return;

    switching = true;
    reindex = { done: 0, total: 0 };
    // 進捗 SSE を購読してから switch を投げる(取りこぼし防止)。
    closeReindex?.();
    closeReindex = openReindexEvents({
      onProgress: (ev) => {
        reindex = { done: ev.done, total: ev.total };
      },
      onComplete: async () => {
        reindex = null;
        switching = false;
        pendingEmbedding = ''; // 未選択へ戻す('' 正規化)
        closeReindex?.();
        closeReindex = null;
        await settingsStore.load();
        pushToast(`埋め込みモデルを「${target}」に切り替えました`, 'success');
      },
      onError: (ev) => {
        reindex = null;
        switching = false;
        closeReindex?.();
        closeReindex = null;
        pushToast(`再インデックスに失敗しました: ${ev.message}`, 'error');
      },
    });

    try {
      await settingsApi.switchEmbedding(target);
    } catch (e) {
      reindex = null;
      switching = false;
      closeReindex?.();
      closeReindex = null;
      pushToast(e instanceof Error ? e.message : String(e), 'error');
    }
  }
</script>
```
  > 注: `onMount`(`settingsStore.load()` + `modelsStore.load()`)は既存/Task 3 のものをそのまま使う。本タスクで `onMount` を再宣言しないこと(二重登録になる)。Task 3 が `chatModelNames`/`onDefaultModelChange` を追記していない(= 実行順違反)場合は `old_string` が一致しないので、先に Task 3 を適用すること。

- [ ] **Step 6: 埋め込みモデル行のみを `<select>` 化し、`</dl>` の後に警告/進捗 UI を追加(部分編集)**
  既定モデル(LLM)行は **Task 3 が入れた `<select>` を維持**し、本タスクは**埋め込みモデルの `<dt>/<dd>` だけ**を `<select>` 化する。さらに `</dl>` の直後へ警告バナー/注記/再インデックスボタン/進捗を挿入する。LLM 既定行・エンドポイント行・`<dl>` 構造は触らない(全置換禁止)。

  **Edit 6-1(埋め込み行の `<dd>` を `<select>` 化)**: Task 3 適用後も埋め込み行は元のまま(`<code>` 表示)なので、その `<dt>/<dd>` だけを差し替える。`old_string`:
```svelte
            <dt>埋め込みモデル</dt>
            <dd><code>{settingsStore.settings.ollama.embedding_model}</code></dd>
          </dl>
```
  `new_string`:
```svelte
            <dt>埋め込みモデル</dt>
            <dd>
              <select
                class="emb-select"
                bind:value={pendingEmbedding}
                disabled={switching}
                aria-label="埋め込みモデル"
              >
                <option value="">{curEmbeddingModel ?? '(未設定)'}(現在)</option>
                {#each embeddingModels as m (m.name)}
                  {#if m.name !== curEmbeddingModel}
                    <option value={m.name}>
                      {m.name}{m.embedding_dim ? ` (${m.embedding_dim}次元)` : ''}
                    </option>
                  {/if}
                {/each}
              </select>
            </dd>
          </dl>
```
  > 注(finding 15 反映済み): 現在/未選択 option は `<option value="">…(現在)</option>`(空文字)とし、`pendingEmbedding`(Step 5 で `string`、初期 `''`)と整合させる。`<option value={null}>` のような null 値は HTML で文字列化してぶれるため使わない。Task 3/4 の `value=""`=「現行/未選択」割り当てと統一済み。

  **Edit 6-2(`</dl>` の直後に警告/注記/ボタン/進捗を挿入)**: 上の Edit 6-1 で残した `</dl>` の直後に、以下のブロックを挿入する。`old_string` は section==='models' の `</dl>` から次の `{:else if section === 'gen'}` までの境界。`old_string`:
```svelte
          </dl>
        {:else if section === 'gen'}
```
  `new_string`:
```svelte
          </dl>

          {#if dimWarning}
            <div class="emb-warn" role="alert">
              選択したモデルは {newDim} 次元です。現在のインデックスは {curDim} 次元(既存チャンクは
              {curEmbeddingModel})。切り替えると<strong>全ソースを再インデックス</strong>します(数分かかる場合があります)。
            </div>
          {:else if sameDimNotice}
            <div class="emb-notice" role="note">
              次元は同じですが埋め込み空間が変わるため<strong>再インデックス推奨</strong>です。切り替えると全ソースを再インデックスします。
            </div>
          {/if}

          {#if switchTarget && !switching}
            <div class="emb-actions">
              <button class="emb-btn primary" onclick={confirmSwitch}>
                再インデックスして切替
              </button>
            </div>
          {/if}

          {#if switching}
            <div class="emb-progress">
              <div class="emb-bar">
                <div
                  class="emb-bar-fill"
                  style:width={reindex && reindex.total > 0
                    ? `${Math.round((reindex.done / reindex.total) * 100)}%`
                    : '8%'}
                ></div>
              </div>
              <span class="emb-progress-text">
                {#if reindex && reindex.total > 0}
                  再インデックス中… {reindex.done} / {reindex.total}
                {:else}
                  再インデックスを準備中…
                {/if}
              </span>
            </div>
          {/if}
        {:else if section === 'gen'}
```

  > 注: この `new_string` は `</dl>` の直後から始まり、末尾で `{:else if section === 'gen'}`(= 元の次ブランチ)へ再接続する。これにより `section==='models'` ブロックの `{#if}…{:else if}` 連鎖が壊れない。LLM 既定行(Task 3 の `<select>`)・エンドポイント行・`<dl>` は本 Edit の範囲外でそのまま残る。

- [ ] **Step 7: 警告バナー・進捗バー・セレクトのスタイルを追加**
  同ファイルの `<style>` 内、末尾(`.err { color: var(--color-error); }` の閉じ括弧の後、`</style>` の直前)に以下を追記する。

```css
  .emb-select {
    font: inherit;
    font-size: 13px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: 5px 9px;
    background: var(--color-bg);
    min-width: 240px;
  }

  .emb-warn,
  .emb-notice {
    margin-top: var(--space-3);
    padding: 10px 12px;
    border-radius: var(--radius-md);
    font-size: 12px;
    line-height: 1.6;
  }

  .emb-warn {
    background: #fff4e5;
    border: 1px solid #f0c27a;
    color: #8a5300;
  }

  .emb-notice {
    background: var(--color-bg-elevated);
    border: 1px solid var(--color-border);
    color: var(--color-fg-muted);
  }

  .emb-actions {
    margin-top: var(--space-3);
  }

  .emb-btn {
    border: 1px solid var(--color-border);
    background: var(--color-bg);
    color: var(--color-fg);
    border-radius: var(--radius-md);
    padding: 7px 14px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
  }

  .emb-btn.primary {
    background: var(--color-accent);
    border-color: var(--color-accent);
    color: #fff;
  }

  .emb-progress {
    margin-top: var(--space-4);
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    max-width: 360px;
  }

  .emb-bar {
    height: 8px;
    border-radius: 999px;
    background: var(--color-bg-elevated);
    overflow: hidden;
  }

  .emb-bar-fill {
    height: 100%;
    background: var(--color-accent);
    transition: width 0.2s ease;
  }

  .emb-progress-text {
    font-size: 12px;
    color: var(--color-fg-muted);
  }
```

- [ ] **Step 8: 型チェックを通す(成功確認)**
  Run: `cd apps/web && npm run check`
  Expected: PASS(0 errors)。Step2 で観測したエラーが解消し、`ModelInfo.kind`/`embedding_dim`・`OllamaSettings.embedding_dim`・`switchEmbedding`・`openReindexEvents` の参照が全て型解決すること。
  もし `svelte-check` が `style:width` や `role="note"` で警告のみ出す場合は許容(error 0 を確認)。

- [ ] **Step 9: 本番ビルドの健全性確認**
  Run: `cd apps/web && npm run build`
  Expected: PASS。`dist/` に出力されること。
  注(既知問題): `apps/web/dist/.gitkeep` が `build` で消える/再生成されない場合があるため、commit 前に存在を確認し、無ければ復元する。
  Run: `cd apps/web && test -f dist/.gitkeep || (mkdir -p dist && : > dist/.gitkeep)`
  Expected: 終了コード 0(`dist/.gitkeep` が存在する)。

- [ ] **Step 10: コミット**
  Run:
  ```
  git add apps/web/src/lib/api/types.ts apps/web/src/lib/api/settings.ts apps/web/src/lib/api/reindexEvents.ts apps/web/src/routes/settings/+page.svelte apps/web/dist/.gitkeep
  git commit -m "feat(web): 設定に埋め込みモデルselect・次元警告・再インデックス進捗(SSE)を追加"
  ```
  Expected: 1 commit 作成。trailer は付けない。

- [ ] **Step 11: 視覚検証(Playwright 実機ゲート・スクショ必須)**
  GUI 変更のため自動テスト GREEN だけでの PASS は禁止。実機で以下を確認しスクショを残す(各 Step で `browser_take_screenshot`)。
  事前: バックエンド起動 `uv run --extra recording uvicorn apps.api.main:app --port 8765`、フロント `cd apps/web && npm run dev`。FE 変更反映のため `?cb=<timestamp>` を付けて再取得(MEMORY: dev-server gotchas)。

  - [ ] `browser_navigate` で `http://localhost:5173/settings?cb=<ts>`(または dev サーバの実ポート)。左ナビ「モデル・Ollama」をクリック。
  - [ ] **スクショ1**: 埋め込みモデルが `<select>`(embedding/both のみが選択肢、現行モデルが先頭「(現在)」)になっていること。
  - [ ] `browser_select_option` で現行と**異なる次元**のモデルを選択 → **スクショ2**: 「選択したモデルは N 次元です。現在のインデックスは M 次元(既存チャンクは …)。…全ソースを再インデックス…」のオレンジ警告バナー + 「再インデックスして切替」ボタンが表示されること。
  - [ ] 現行と**同次元の別モデル**を選択(存在すれば)→ **スクショ3**: dim 警告ではなく「再インデックス推奨(埋め込み空間が変わる)」注記が出ること。
  - [ ] 「再インデックスして切替」→ `window.confirm` を `browser_handle_dialog`(accept)で承認 → **スクショ4**: 進捗バー + 「再インデックス中… done / total」が出ること(Task7 の SSE が動いていれば進捗が更新される)。
  - [ ] 完了後 → **スクショ5**: トースト「埋め込みモデルを『…』に切り替えました」、`<select>` の「(現在)」表示が新モデルに更新されていること(`settingsStore.load()` 反映)。
  - [ ] ページ再読込(`?cb=<新ts>`)→ **スクショ6**: 切替後のモデルが現行として永続化されていること(settings.json 反映)。
  - [ ] `browser_console_messages` でエラーが無いこと(EventSource の 404/parse エラーが出ていないこと)。
  もし Task7 の SSE URL / イベント名が本タスクの想定(`/api/settings/events`、`reindex_*`)と異なっていた場合、`reindexEvents.ts` の URL とリスナ名のみを実物へ合わせて再検証する(他ファイルは変更不要)。視覚 OK を確認するまで本タスクを完了扱いにしない。

---

補足(実装者向け・実在性メモ):
- 現行次元(`curDim`)は `settings.ollama.embedding_dim` から取得する設計。`/api/stats`(`Stats` 型)には次元フィールドが無いため使わない。`embedding_dim` を `/api/settings` が返すのは **Task5 Step 13b の責務**(Interfaces.Consumes 参照)。万一それが `embedding_dim` を `/api/settings` でなく `/api/models` のみに載せた場合は、`curDim` の取得元を「`embeddingModels` から `name === curEmbeddingModel` の `embedding_dim`」へ差し替える(`$derived` 1 行の変更で済む)。
- 既存 SSE(`api/events.ts` / `stores/events.svelte.ts`)はノート単位の `source_status` 専用。再インデックスはノート横断のため流用せず、本タスクで `reindexEvents.ts` を新設している(バックエンドの `ctx.sse.subscribe(topic)` ベースのトピック購読方式と整合)。
- LLM 既定の `<select>` 化(spec (B-1))・ノート detail のモデルピッカー(spec (B-2))は本タスクのスコープ外(別タスク)。本タスクでは「既定モデル(LLM)」を読取専用 `<code>` のまま残している。

# 録音自動命名・ソース名編集 + しきい値表示改善 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. TDD(失敗テスト→fail確認→最小実装→pass確認→commit)。GUI変更は各機能末尾の Playwright 実機スクショ検証ゲート(自動テストGREENのみでのPASS禁止)。

**Goal:** (a) 名前採用しきい値スライダーの値表示を明確化、(c-1) 録音タイトルのLLM自動命名(設定ON/OFF)、(c-2) 全ソース名のインライン編集。

**Architecture:** FastAPI(`apps/api/`)+ 純ドメイン(`core/`)+ SvelteKit(Svelte 5 runes, `apps/web/`)。SQLite + Qdrant + Ollama。設計仕様: `docs/specs/2026-06-19-recording-naming-design.md`(決定は確定)。

**Tech Stack:** Python(uv/pytest/ruff)、TypeScript + Svelte 5 runes(svelte-check/vite build)、Ollama `OllamaGateway.generate`。

**ブランチ:** `feature/recording-naming`(`feature/rag-ux-improvements` の上に積む。master 直接編集禁止)。

## Global Constraints
- 新規ランタイム依存なし。LLM タイトル生成は既存 `OllamaGateway.generate` を流用。
- 自動命名は **best-effort**(失敗・空セグメントでも READY を阻害しない)。`auto_title` 既定 ON、設定でOFF可(既存 settings.json 永続化)。retry(再生成)時も同じく再命名。
- 既存テストを壊さない(`uv run pytest` 緑)。`cd apps/web && npm run check` 0 errors(既存6 warnings のみ許容)、`npm run build` 成功。
- リネームは全 kind のソースに適用。空/空白のみのタイトルは 422。インライン編集トリガーはカード選択(onSelect)と分離(stopPropagation)。
- コミット trailer なし。GUI 変更は Playwright 実機検証ゲート。

## 実装順(スプリント)
**AA(しきい値表示)→ CB(自動命名)→ CR(名前編集)**。CB が `core/storage/sources_repo.py::update_source_title` を追加し、CR はそれを利用する(CR は重複追加しない)。各機能内のタスクは記載順。

---

## (a) 名前採用しきい値スライダーの値表示改善

### Task AA.1 — ヒント文にスライダー現在値を埋め込み、値=しきい値だと明示する

**Files**
- Modify: `apps/web/src/lib/components/settings/AudioSettingsSection.svelte`
- Test (gate, no new test file): `cd apps/web && npm run check` + `npm run build` + Playwright 視覚ゲート(controller 実行)

**Interfaces**
- Consumes: `draft.name_threshold: number`(`AudioSettings` の既存フィールド。既に `bind:value` で range にバインド済み、live 更新される)。
- Produces: なし(純表示変更。props / イベント / store 契約の変更なし。`draft` の読み取りのみ)。

**Steps**

1. (RED — 視認性の現状確認 / 手動) 変更前のベースラインを確認する。設定パネルを開き、現状の「名前採用のしきい値」行が `0.65` のような数値 `.mono` と、その値を参照しないヒント `未満は「相手N」のまま` の2要素に分かれていて、表示中の数値が「しきい値」だと一目で結びつかないことを目視確認する(これが解消対象)。コード変更は次ステップ。

2. (GREEN — 最小実装) `AudioSettingsSection.svelte` の名前採用しきい値行の `.ctl` 内、`.mono` span とヒント span を、現在値をインラインに埋め込んだ単一の説明文へ統合する。`.mono` は値の視認性のため残し、ヒント文中で「この値」が直前の `.mono` を指すよう接続して値=しきい値を明示する。

   現状(L257-258):
   ```svelte
        <span class="mono">{draft.name_threshold.toFixed(2)}</span>
        <span class="hint-text">未満は「相手N」のまま</span>
   ```
   を、以下へ置き換える:
   ```svelte
        <span class="mono">{draft.name_threshold.toFixed(2)}</span>
        <span class="hint-text">この値 ({draft.name_threshold.toFixed(2)}) 未満は「相手N」のまま</span>
   ```
   置換は Edit で次のとおり行う(`old_string` は L257-258 の2行をインデント込みで完全一致):
   - old_string:
     ```
        <span class="mono">{draft.name_threshold.toFixed(2)}</span>
        <span class="hint-text">未満は「相手N」のまま</span>
     ```
   - new_string:
     ```
        <span class="mono">{draft.name_threshold.toFixed(2)}</span>
        <span class="hint-text">この値 ({draft.name_threshold.toFixed(2)}) 未満は「相手N」のまま</span>
     ```
   この行の構造(`.range-input` の input → `.mono` → `.hint-text`)・CSS クラス・`bind:value` は一切変えない。`{draft.name_threshold.toFixed(2)}` はヒント内でも `.mono` と同じ式なので live 更新は range のドラッグに追従する。

3. (型/ビルドゲート — RED→GREEN) 静的検査とビルドを通す。
   - コマンド: `cd apps/web && npm run check`
   - 期待(PASS): `svelte-check found 0 errors and 0 warnings`(`draft.name_threshold` は既存の数値フィールドで `toFixed` 利用も既出のため新規型エラーは出ない。出た場合は `draft` の null ガードなど既存と同じ理由なので、本行が原因でないことを差分で確認)。
   - 続けて: `cd apps/web && npm run build`
   - 期待(PASS): Vite build がエラーなく `apps/web/dist/` を出力して終了(exit 0)。

4. (視覚ゲート — controller 実行) Playwright 実機検証(CLAUDE.md「GUI変更は自動テストGREENだけでPASS禁止、Evaluatorスクショ必須」に従う)。controller/Evaluator が以下を確認:
   - 設定モーダルを開き「話者分離 / 名前予想」グループの「名前採用のしきい値」行をスクショ。
   - range スライダーをドラッグして値を変える(例: 0.65 → 0.40)と、`.mono` とヒント文中の `(0.40)` が**両方同時に**追従し、「この値 (0.40) 未満は「相手N」のまま」と読めて値=しきい値の対応が一目で分かること。
   - レイアウト崩れ(`.hint-text` の折り返し・はみ出し)がないことをスクショで確認。
   - NG時は self-fix 最大3回(例: 値が二重に冗長なら `.mono` を削りヒント単独 `この値 ({...}) 未満は「相手N」のまま` に寄せる等、いずれも純表示で再ゲート)。

5. (COMMIT) 視覚ゲート PASS 後にコミットする。
   - `cd apps/web` は不要(リポジトリルート `E:\00_Git\10_NotebookOllama` で実行)。
   - `git add apps/web/src/lib/components/settings/AudioSettingsSection.svelte`
   - `git commit -m "設定: 名前採用しきい値のヒントに現在値を埋め込み値=しきい値を明示"`
   - trailer は付けない(Co-Authored-By なし)。ブランチは `feature/recording-naming`(master 直接コミット禁止)。

---

関連ファイル(すべて絶対パス):
- 変更対象: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\settings\AudioSettingsSection.svelte`(該当行 L246-260)
- 設計仕様(FIXED): `E:\00_Git\10_NotebookOllama\docs\specs\2026-06-19-recording-naming-design.md`(§3 (a))
- Playwright 設定: `E:\00_Git\10_NotebookOllama\apps\web\playwright.config.ts`

load-bearing な差分(置換前→置換後の唯一の変更箇所):
```svelte
-    <span class="hint-text">未満は「相手N」のまま</span>
+    <span class="hint-text">この値 ({draft.name_threshold.toFixed(2)}) 未満は「相手N」のまま</span>

---

## c-1 Recording auto-title via LLM, with a settings toggle

This sub-feature adds an `auto_title` audio setting (default ON), a new pure title-inference module, wires it into the recording pipeline as a best-effort step, persists the inferred title via a new repo function, threads the flag through the shared dispatch helper (so both stop and retry re-title), and exposes the toggle in the settings API + frontend types + settings UI.

All backend tests run with `uv run pytest` from repo root `E:\00_Git\10_NotebookOllama`. Frontend gates run from `apps/web`.

---

### Task CB.1 — `auto_title` setting (config + API schema + API router + frontend type)

Add the `auto_title: bool = True` field end-to-end through the read path (config → schema → `get_settings`) and the frontend type. The settings PUT path needs no change because `put_audio_settings` round-trips the whole `AudioSettingsSchema` via `model_dump()`.

**Files**
- Modify: `core/config.py` (`AudioSettings`)
- Modify: `apps/api/schemas/settings.py` (`AudioSettingsSchema`)
- Modify: `apps/api/routers/settings.py` (`get_settings` audio block)
- Modify: `apps/web/src/lib/api/types.ts` (`AudioSettings`)
- Test: `tests/integration/test_api/test_settings_auto_title.py` (new)

**Interfaces**
- Produces: `AudioSettings.auto_title: bool` (default `True`) — pydantic model field on `core.config.AudioSettings`.
- Produces: `AudioSettingsSchema.auto_title: bool` (required field) — present in `GET /api/settings` `audio` block and accepted/echoed by `PUT /api/settings/audio`.
- Consumes (frontend): `AudioSettings.auto_title: boolean` in `apps/web/src/lib/api/types.ts`.

**Steps**

1. **(red) Write the failing integration test.** Create `tests/integration/test_api/test_settings_auto_title.py`:

   ```python
   """GET /api/settings の audio に auto_title(既定 True)が載り、
   PUT /api/settings/audio で round-trip することを検証する統合テスト。"""

   import pytest
   from fastapi.testclient import TestClient

   from apps.api.main import create_app


   @pytest.fixture
   def client(tmp_path, monkeypatch):
       monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
       app = create_app()
       with TestClient(app) as c:
           yield c


   def test_get_settings_exposes_auto_title_default_true(client):
       r = client.get("/api/settings")
       assert r.status_code == 200, r.text
       audio = r.json()["audio"]
       assert audio["auto_title"] is True


   def test_put_audio_settings_round_trips_auto_title(client):
       audio = client.get("/api/settings").json()["audio"]
       audio["auto_title"] = False
       r = client.put("/api/settings/audio", json=audio)
       assert r.status_code == 200, r.text
       assert r.json()["auto_title"] is False
       # 永続化 + in-memory 反映: 再取得でも False。
       assert client.get("/api/settings").json()["audio"]["auto_title"] is False
   ```

2. **(run-fail)** Run:
   ```
   uv run pytest tests/integration/test_api/test_settings_auto_title.py -q
   ```
   Expected: both tests fail. `test_get_settings_exposes_auto_title_default_true` fails with `KeyError: 'auto_title'` (the `audio` block has no such key); the round-trip test fails at validation/`KeyError` for the same reason.

3. **(green) Add the config field.** In `core/config.py`, in `AudioSettings`, add `auto_title` after `keep_audio`:

   ```python
       storage_format: str = "aac"         # aac | opus | mp3 | wav
       storage_bitrate_kbps: int = 64
       keep_audio: bool = True
       auto_title: bool = True             # 停止後パイプラインで LLM がタイトル自動命名
   ```

4. **(green) Add the schema field.** In `apps/api/schemas/settings.py`, in `AudioSettingsSchema`, add `auto_title` after `keep_audio`:

   ```python
       storage_format: Literal["aac", "opus", "mp3", "wav"]
       storage_bitrate_kbps: int
       keep_audio: bool
       auto_title: bool
   ```

5. **(green) Surface it in `get_settings`.** In `apps/api/routers/settings.py`, in the `AudioSettingsSchema(...)` constructed inside `get_settings`, add the field after `keep_audio`:

   ```python
               storage_format=cfg.audio.storage_format,
               storage_bitrate_kbps=cfg.audio.storage_bitrate_kbps,
               keep_audio=cfg.audio.keep_audio,
               auto_title=cfg.audio.auto_title,
   ```

6. **(green) Add the frontend type.** In `apps/web/src/lib/api/types.ts`, in `interface AudioSettings`, add the field after `keep_audio`:

   ```ts
     storage_format: "aac" | "opus" | "mp3" | "wav";
     storage_bitrate_kbps: number;
     keep_audio: boolean;
     auto_title: boolean;
   ```

7. **(run-pass)** Run:
   ```
   uv run pytest tests/integration/test_api/test_settings_auto_title.py -q
   ```
   Expected: 2 passed.

8. **(commit)**
   ```
   git add core/config.py apps/api/schemas/settings.py apps/api/routers/settings.py apps/web/src/lib/api/types.ts tests/integration/test_api/test_settings_auto_title.py
   git commit -m "feat(recording): auto_title 設定を config/API/型に追加(既定ON)"
   ```

---

### Task CB.2 — `core/recording/title_inference.py` (pure title generator)

New pure module mirroring `name_inference.py`: a prompt builder, a parser that strips quotes/preamble to one line, and an async `infer_title` that returns `""` on empty input or any LLM exception.

**Files**
- Create: `core/recording/title_inference.py`
- Test: `tests/unit/test_title_inference.py` (new)

**Interfaces**
- Produces: `build_title_prompt(segments: list[dict]) -> str` — concatenates `s["text"]`, truncates to a fixed character budget, asks for one concise title (~全角20文字), title-only.
- Produces: `parse_title(raw: str) -> str` — first non-empty line, surrounding quotes/`「」`/`：`-preamble stripped; `""` when nothing usable.
- Produces: `async infer_title(segments: list[dict], llm, model: str) -> str` — `""` on empty segments; calls `llm.generate(model=..., prompt=..., options={"temperature": 0})`; `""` on exception.
- Consumes: `llm.generate(*, model: str, prompt: str, options) -> str` (the `_GatewayLike` shape already used by `infer_names`).

> Note: `segments` here is the corrected `list[Segment]` from the pipeline, but this module only reads `.text`. The pipeline (Task CB.4) adapts `Segment` → `{"speaker", "text"}` dicts exactly like the existing `infer_names` call site, so `title_inference` consumes plain dicts and stays pure/testable.

**Steps**

1. **(red) Write the failing unit test.** Create `tests/unit/test_title_inference.py`:

   ```python
   import asyncio

   from core.recording.title_inference import (
       build_title_prompt,
       infer_title,
       parse_title,
   )


   def test_build_prompt_includes_text_and_instruction():
       segs = [{"speaker": "あなた", "text": "来期の予算について"},
               {"speaker": "相手1", "text": "資料を共有します"}]
       prompt = build_title_prompt(segs)
       assert "来期の予算について" in prompt
       assert "資料を共有します" in prompt
       assert "タイトル" in prompt


   def test_build_prompt_truncates_long_text():
       segs = [{"speaker": "あなた", "text": "あ" * 5000}]
       prompt = build_title_prompt(segs)
       # 本文は打ち切られる(プロンプト全体が原文5000字を丸ごと含まない)。
       assert prompt.count("あ") < 5000


   def test_parse_strips_quotes_and_preamble():
       assert parse_title('「来期予算レビュー会議」') == "来期予算レビュー会議"
       assert parse_title('"Q3 Planning"') == "Q3 Planning"
       assert parse_title("タイトル: 採用面談の振り返り") == "採用面談の振り返り"


   def test_parse_takes_first_nonempty_line():
       assert parse_title("\n\n  プロジェクト定例  \n補足説明") == "プロジェクト定例"


   def test_parse_empty_returns_empty():
       assert parse_title("") == ""
       assert parse_title("   \n  ") == ""


   def test_infer_title_returns_parsed_title():
       class _LLM:
           async def generate(self, *, model, prompt, options=None):
               return "「来期予算レビュー」"

       segs = [{"speaker": "あなた", "text": "来期の予算を見直したい"}]
       out = asyncio.run(infer_title(segs, _LLM(), "qwen2.5:14b"))
       assert out == "来期予算レビュー"


   def test_infer_title_empty_segments_returns_empty():
       class _LLM:
           async def generate(self, *, model, prompt, options=None):
               raise AssertionError("LLM must not be called for empty segments")

       assert asyncio.run(infer_title([], _LLM(), "qwen2.5:14b")) == ""


   def test_infer_title_swallows_llm_exception():
       class _BoomLLM:
           async def generate(self, *, model, prompt, options=None):
               raise RuntimeError("boom")

       segs = [{"speaker": "あなた", "text": "x"}]
       assert asyncio.run(infer_title(segs, _BoomLLM(), "qwen2.5:14b")) == ""
   ```

2. **(run-fail)** Run:
   ```
   uv run pytest tests/unit/test_title_inference.py -q
   ```
   Expected: collection error / `ModuleNotFoundError: No module named 'core.recording.title_inference'` (module does not exist yet).

3. **(green) Create the module.** Write `core/recording/title_inference.py`:

   ```python
   from __future__ import annotations

   _PROMPT_HEADER = (
       "以下は会議の文字起こしです。内容を表す簡潔なタイトルを 1 つだけ出力してください。\n"
       "全角20文字程度、体言止め。タイトルのみを1行で返し、引用符や前置きは付けないこと。\n\n"
   )

   # 本文の打ち切り長(文字数)。長い会議でもプロンプトを抑え、先頭の話題で命名する。
   _MAX_BODY_CHARS = 2000


   def build_title_prompt(segments: list[dict]) -> str:
       body = "\n".join(s.get("text", "") for s in segments)
       body = body[:_MAX_BODY_CHARS]
       return _PROMPT_HEADER + "文字起こし:\n" + body


   def parse_title(raw: str) -> str:
       for line in (raw or "").splitlines():
           line = line.strip()
           if not line:
               continue
           # 「タイトル:」「Title:」等の前置きを除去(最後のコロン以降を採用)。
           for sep in ("：", ":"):
               if sep in line:
                   head, _, tail = line.rpartition(sep)
                   if head.strip():  # コロン前に語があれば前置きとみなす
                       line = tail.strip()
                       break
           # 前後の引用符 / 鉤括弧を除去。
           line = line.strip("\"'「」『』 　")
           if line:
               return line
       return ""


   async def infer_title(segments: list[dict], llm, model: str) -> str:
       if not segments:
           return ""
       try:
           prompt = build_title_prompt(segments)
           raw = await llm.generate(model=model, prompt=prompt, options={"temperature": 0})
           return parse_title(raw)
       except Exception:
           return ""
   ```

4. **(run-pass)** Run:
   ```
   uv run pytest tests/unit/test_title_inference.py -q
   ```
   Expected: 7 passed.

5. **(commit)**
   ```
   git add core/recording/title_inference.py tests/unit/test_title_inference.py
   git commit -m "feat(recording): LLM タイトル自動命名モジュール title_inference を追加"
   ```

---

### Task CB.3 — `sources_repo.update_source_title`

Add a focused repo function that updates only `title` + `updated_at` (independent of status), so the pipeline can persist the inferred title best-effort without touching the status machine.

**Files**
- Modify: `core/storage/sources_repo.py`
- Test: `tests/integration/test_storage/test_update_source_title.py` (new)

**Interfaces**
- Produces: `update_source_title(conn: sqlite3.Connection, source_id: str, title: str) -> SourceRecord` — runs `UPDATE sources SET title=?, updated_at=? WHERE id=?` using `_now()`, then returns the refreshed `get_source(conn, source_id)`.
- Consumes: existing `get_source`, `_now`, `SourceRecord`.

**Steps**

1. **(red) Write the failing test.** Create `tests/integration/test_storage/test_update_source_title.py`:

   ```python
   """update_source_title が title と updated_at のみを更新し、status は不変なことを検証。"""

   import sqlite3

   from core.storage import sources_repo
   from core.storage.database import migrate
   from core.storage.sources_repo import SourceStatus


   def _conn() -> sqlite3.Connection:
       c = sqlite3.connect(":memory:")
       c.row_factory = sqlite3.Row
       migrate(c)
       c.execute(
           "INSERT INTO notebooks(id,name,created_at,updated_at) VALUES('nb','n','t','t')"
       )
       return c


   def test_update_source_title_sets_title_keeps_status():
       conn = _conn()
       src = sources_repo.create_source(
           conn, notebook_id="nb", kind="recording", title=None, origin="録音"
       )
       sources_repo.update_source_status(
           conn, src.id, status=SourceStatus.READY
       )

       updated = sources_repo.update_source_title(conn, src.id, "来期予算レビュー")
       assert updated.title == "来期予算レビュー"
       # status は触らない。
       assert updated.status is SourceStatus.READY
       # updated_at は前進する。
       assert updated.updated_at >= src.updated_at
       # 永続化されている。
       assert sources_repo.get_source(conn, src.id).title == "来期予算レビュー"
   ```

2. **(run-fail)** Run:
   ```
   uv run pytest tests/integration/test_storage/test_update_source_title.py -q
   ```
   Expected: fails with `AttributeError: module 'core.storage.sources_repo' has no attribute 'update_source_title'`.

3. **(green) Add the function.** In `core/storage/sources_repo.py`, insert immediately after `update_source_status` (before `upsert_dedupe`):

   ```python
   def update_source_title(
       conn: sqlite3.Connection,
       source_id: str,
       title: str,
   ) -> SourceRecord:
       get_source(conn, source_id)  # 存在チェック (無ければ STORAGE_NOT_FOUND)
       conn.execute(
           "UPDATE sources SET title=?, updated_at=? WHERE id=?",
           (title, _now(), source_id),
       )
       return get_source(conn, source_id)
   ```

4. **(run-pass)** Run:
   ```
   uv run pytest tests/integration/test_storage/test_update_source_title.py -q
   ```
   Expected: 1 passed.

5. **(commit)**
   ```
   git add core/storage/sources_repo.py tests/integration/test_storage/test_update_source_title.py
   git commit -m "feat(storage): update_source_title を追加(title のみ更新)"
   ```

---

### Task CB.4 — Wire auto-title into `RecordingPipeline.run`

Add an `auto_title_enabled: bool = True` parameter and, after correction produces `corrected` segments, best-effort infer a title and persist it via `update_source_title`. Placed after the `correct` step (so it titles from the corrected transcript) and before the `CHUNKING` status update, wrapped in try/except so failure never blocks READY.

**Files**
- Modify: `core/recording/recording_pipeline.py`
- Test: `tests/integration/test_recording_pipeline_title.py` (new)

**Interfaces**
- Consumes: `infer_title(segments, llm, model) -> str` (Task CB.2), `update_source_title(conn, source_id, title)` (Task CB.3).
- Produces: `RecordingPipeline.run(..., auto_title_enabled: bool = True)` — when `auto_title_enabled and corrected`, sets `source.title` to the inferred non-empty title; otherwise leaves `title` untouched.

**Steps**

1. **(red) Write the failing test.** Create `tests/integration/test_recording_pipeline_title.py`. It reuses the fake-injection style of `test_recording_pipeline_fake.py` but with a minimal `FakeOllama` whose `generate` returns a title for the title prompt, an echo for correction, and `[]` for name-inference:

   ```python
   """auto_title_enabled の挙動を検証する統合テスト(全依存 fake)。

   - auto_title ON かつ corrected セグメントあり → source.title が設定される。
   - auto_title OFF → title は不変(None のまま)。
   """

   from __future__ import annotations

   import sqlite3
   from pathlib import Path

   import pytest

   from core.recording.recording_pipeline import RecordingPipeline, RecordingPipelineDeps
   from core.recording.transcriber import TranscriptSegment
   from core.storage import sources_repo
   from core.storage.database import migrate


   class FakeTranscriber:
       def transcribe(self, wav_path, *, channel, speaker_id, language="ja", session_id=""):
           if channel == "mic":
               return [
                   TranscriptSegment(
                       id=None, session_id=session_id, channel="mic",
                       start_ms=0, end_ms=1000, speaker_id=speaker_id,
                       text="来期の予算を見直したい", language="ja",
                   ),
               ]
           return []


   class FakeOllama:
       """title プロンプトには固定タイトル、name-inference には空配列、
       校正には番号付きエコーを返す。"""

       async def embed(self, *, model, text):
           return [0.1, 0.2, 0.3]

       async def generate(self, *, model, prompt, options=None):
           if "簡潔なタイトル" in prompt:
               return "「来期予算レビュー」"
           if "実名を推定する" in prompt:
               return "[]"
           lines = []
           for raw in prompt.splitlines():
               stripped = raw.strip()
               if stripped and stripped[0].isdigit() and "." in stripped:
                   num, _, rest = stripped.partition(".")
                   if num.isdigit():
                       lines.append(f"{num}. {rest.strip()}")
           return "\n".join(lines)


   class FakeVectorStore:
       def __init__(self):
           self.upserts: list = []

       def ensure_collection(self):
           pass

       def upsert(self, vectors):
           self.upserts.extend(list(vectors))


   def _conn() -> sqlite3.Connection:
       c = sqlite3.connect(":memory:")
       c.row_factory = sqlite3.Row
       migrate(c)
       c.execute("INSERT INTO notebooks(id,name,created_at,updated_at) VALUES('nb','n','t','t')")
       c.execute(
           "INSERT INTO sources(id,notebook_id,kind,title,status,created_at,updated_at) "
           "VALUES('src','nb','recording',NULL,'pending','t','t')"
       )
       return c


   def _pipeline(conn):
       return RecordingPipeline(
           deps=RecordingPipelineDeps(
               conn=conn, vector_store=FakeVectorStore(), ollama=FakeOllama(),
               embedding_model="bge-m3", broker=None,
           )
       )


   async def test_auto_title_on_sets_source_title(tmp_path: Path):
       conn = _conn()
       await _pipeline(conn).run(
           source_id="src", notebook_id="nb",
           mic_wav=tmp_path / "mic.wav", system_wav=None,
           transcriber=FakeTranscriber(), diarizer=None,
           model="qwen3", diarization_enabled=False, name_inference_enabled=False,
           name_threshold=0.7, auto_title_enabled=True,
       )
       src = sources_repo.get_source(conn, "src")
       assert src.status is sources_repo.SourceStatus.READY
       assert src.title == "来期予算レビュー"


   async def test_auto_title_off_keeps_title_none(tmp_path: Path):
       conn = _conn()
       await _pipeline(conn).run(
           source_id="src", notebook_id="nb",
           mic_wav=tmp_path / "mic.wav", system_wav=None,
           transcriber=FakeTranscriber(), diarizer=None,
           model="qwen3", diarization_enabled=False, name_inference_enabled=False,
           name_threshold=0.7, auto_title_enabled=False,
       )
       src = sources_repo.get_source(conn, "src")
       assert src.status is sources_repo.SourceStatus.READY
       assert src.title is None
   ```

   > The title assertion relies on the prompt containing the literal `簡潔なタイトル`. Confirm `_PROMPT_HEADER` in `title_inference.py` contains that phrase; the header written in Task CB.2 (`内容を表す簡潔なタイトルを 1 つだけ出力`) does. If you reword the header, update this fake's branch condition to match.

2. **(run-fail)** Run:
   ```
   uv run pytest tests/integration/test_recording_pipeline_title.py -q
   ```
   Expected: `test_auto_title_on_sets_source_title` fails — `run()` raises `TypeError: run() got an unexpected keyword argument 'auto_title_enabled'`. (Both tests error for the same reason.)

3. **(green) Add the import.** In `core/recording/recording_pipeline.py`, update the imports block. Change:

   ```python
   from core.recording.segment_correct import Segment, correct_segments_aligned
   from core.storage.chunks_repo import ChunkRecord, insert_chunks
   from core.storage.sources_repo import SourceStatus, update_source_status
   ```
   to:
   ```python
   from core.recording.segment_correct import Segment, correct_segments_aligned
   from core.recording.title_inference import infer_title
   from core.storage.chunks_repo import ChunkRecord, insert_chunks
   from core.storage.sources_repo import (
       SourceStatus,
       update_source_status,
       update_source_title,
   )
   ```

4. **(green) Add the `run` parameter.** In `RecordingPipeline.run`, add `auto_title_enabled` to the signature after `keep_audio`:

   ```python
           storage_format: str = "aac",
           storage_bitrate_kbps: int = 64,
           keep_audio: bool = True,
           auto_title_enabled: bool = True,
       ) -> None:
   ```

5. **(green) Insert the title step after correction.** In `run`, locate the `# --- 4. correct ---` block ending with:

   ```python
           corrected = await correct_segments_aligned(
               all_segments, self._deps.ollama, model
           )

           # --- 5. chunk ------------------------------------------------------
   ```
   Insert the auto-title step between them:
   ```python
           corrected = await correct_segments_aligned(
               all_segments, self._deps.ollama, model
           )

           # --- 4.5 自動タイトル命名 (best-effort, READY を阻害しない) ----------
           # 整文済みトランスクリプトから LLM で簡潔なタイトルを 1 つ予想し、
           # source.title に設定する。失敗・空でもパイプラインは継続する。
           if auto_title_enabled and corrected:
               try:
                   title = await infer_title(
                       [{"speaker": s.speaker, "text": s.text} for s in corrected],
                       self._deps.ollama, model,
                   )
                   if title:
                       update_source_title(conn, source_id, title)
               except Exception:
                   log.warning("recording_auto_title_failed", source_id=source_id)

           # --- 5. chunk ------------------------------------------------------
   ```

6. **(run-pass)** Run:
   ```
   uv run pytest tests/integration/test_recording_pipeline_title.py -q
   ```
   Expected: 2 passed.

7. **(regression)** Run the existing pipeline tests to confirm the new default-`True` parameter and step don't break them:
   ```
   uv run pytest tests/integration/test_recording_pipeline_fake.py -q
   ```
   Expected: all passed. (Those tests don't pass `auto_title_enabled`, so it defaults to `True`; their `FakeOllama.generate` returns the echo branch for the title prompt — a harmless non-empty title that gets stored but isn't asserted against. No assertion in those tests inspects `title`, so they stay green.)

8. **(commit)**
   ```
   git add core/recording/recording_pipeline.py tests/integration/test_recording_pipeline_title.py
   git commit -m "feat(recording): パイプラインに自動タイトル命名を結線(best-effort)"
   ```

---

### Task CB.5 — Thread `auto_title_enabled` through `_dispatch_recording_pipeline`

Pass `auto_title_enabled=a.auto_title` from the shared dispatch helper so both `stop_recording` and `retry_recording` apply (re)titling.

**Files**
- Modify: `apps/api/routers/recordings.py` (`_dispatch_recording_pipeline`)
- Test: `tests/integration/test_api/test_recording_stop_dispatch.py` (extend with one assertion; add one new test for retry)

**Interfaces**
- Consumes: `RecordingPipeline.run(..., auto_title_enabled: bool)` (Task CB.4); `ctx.config.audio.auto_title` (Task CB.1).
- Produces: dispatched `pipeline.run(...)` call now carries `auto_title_enabled=a.auto_title` for both stop and retry.

**Steps**

1. **(red) Extend the existing dispatch test.** In `tests/integration/test_api/test_recording_stop_dispatch.py`, inside `test_stop_dispatches_offline_pipeline_as_background_task`, after the existing line:

   ```python
       assert isinstance(call["name_inference_enabled"], bool)
   ```
   add:
   ```python
       # auto_title flag is threaded from config (default True).
       assert call["auto_title_enabled"] is True
   ```
   Then append a new test at the end of the file that verifies retry also threads the flag (and honors `auto_title=False`):
   ```python
   def test_retry_threads_auto_title_flag(client):
       nb = _create_nb(client)
       fake_pipeline = _FakePipeline()
       client.app.state.ctx.recording_pipeline = fake_pipeline
       # auto_title を OFF にしておく(in-memory config を直接いじる)。
       client.app.state.ctx.config.audio.auto_title = False

       # source(録音)と圧縮済み音源を 1 つ用意する。
       r = client.post(f"/api/notebooks/{nb}/recordings", json={"live_caption": False})
       src_id = r.json()["source_id"]
       rid = r.json()["recording_id"]
       # stop して 1 回目の dispatch を消費。
       client.post(f"/api/notebooks/{nb}/recordings/{rid}/stop")
       fake_pipeline.calls.clear()

       # 再処理に必要な圧縮音源を session dir に置く。
       session_dir = client.app.state.ctx.config.sources_dir / src_id
       session_dir.mkdir(parents=True, exist_ok=True)
       (session_dir / "mic.m4a").write_bytes(b"\x00" * 256)

       r_retry = client.post(f"/api/notebooks/{nb}/recordings/{src_id}/retry")
       assert r_retry.status_code == 200, r_retry.text
       assert len(fake_pipeline.calls) == 1
       assert fake_pipeline.calls[0]["auto_title_enabled"] is False
   ```

   > `_resolve_audio_path(base, "mic")` resolves the per-channel compressed file. `mic.m4a` is the AAC default extension; if `_resolve_audio_path` expects a different stem/extension, place the file matching it (read `apps/api/routers/audio.py::_resolve_audio_path` if the retry call returns 422 "no audio to re-embed").

2. **(run-fail)** Run:
   ```
   uv run pytest tests/integration/test_api/test_recording_stop_dispatch.py -q
   ```
   Expected: both the extended assertion and the new `test_retry_threads_auto_title_flag` fail with `KeyError: 'auto_title_enabled'` (the helper doesn't pass it yet).

3. **(green) Pass the flag in the helper.** In `apps/api/routers/recordings.py`, in `_dispatch_recording_pipeline`, in the `background.add_task(ctx.recording_pipeline.run, ...)` call, add `auto_title_enabled` after `keep_audio`:

   ```python
           storage_format=a.storage_format,
           storage_bitrate_kbps=a.storage_bitrate_kbps,
           keep_audio=a.keep_audio,
           auto_title_enabled=a.auto_title,
       )
   ```

4. **(run-pass)** Run:
   ```
   uv run pytest tests/integration/test_api/test_recording_stop_dispatch.py -q
   ```
   Expected: all tests passed (3: the two original + the new retry test).

5. **(regression)** Run the broader recording API + pipeline suites to confirm nothing regressed:
   ```
   uv run pytest tests/integration/test_api/test_recording_stop_dispatch.py tests/integration/test_recording_pipeline_fake.py tests/integration/test_recording_pipeline_title.py -q
   ```
   Expected: all passed.

6. **(commit)**
   ```
   git add apps/api/routers/recordings.py tests/integration/test_api/test_recording_stop_dispatch.py
   git commit -m "feat(recording): stop/retry の dispatch に auto_title_enabled を配線"
   ```

---

### Task CB.6 — Settings UI toggle for auto-title

Add a switch for `auto_title` to `AudioSettingsSection.svelte`, in the 「話者分離 / 名前予想(停止後の高精度変換)」 group (it is a post-stop high-accuracy-conversion feature, alongside the existing LLM name-inference switch). Pure UI; gated by `npm run check` + `npm run build` + a Playwright visual gate run by the controller.

**Files**
- Modify: `apps/web/src/lib/components/settings/AudioSettingsSection.svelte`
- Test: none (frontend pure-UI; gated by `npm run check` / `npm run build` / Playwright visual gate)

**Interfaces**
- Consumes: `draft.auto_title: boolean` (from `AudioSettings`, Task CB.1) — bound via the same switch pattern as `name_inference_llm`; persisted through the existing `save()` → `settingsApi.putAudio(draft)` path (no new wiring).
- Produces: a `role="switch"` control with `aria-label="録音タイトルの自動命名"` toggling `draft.auto_title`.

**Steps**

1. **(green) Add the switch row.** In `apps/web/src/lib/components/settings/AudioSettingsSection.svelte`, inside the 「話者分離 / 名前予想」 group, append a new row immediately after the `name_inference_llm` row's closing `</div>` and before the 「名前採用のしきい値」 row. Locate:

   ```svelte
           ><i></i></button>
         </div>
       </div>
       <div class="row">
         <div class="lab">名前採用のしきい値</div>
   ```
   Insert the new row between the two `<div class="row">` blocks:
   ```svelte
           ><i></i></button>
         </div>
       </div>
       <div class="row">
         <div class="lab">録音タイトルの自動命名<small>停止後に会議内容から LLM がタイトルを予想して設定(後で編集可)</small></div>
         <div class="ctl">
           <button
             class="switch"
             class:off={!draft.auto_title}
             role="switch"
             aria-checked={draft.auto_title}
             aria-label="録音タイトルの自動命名"
             onclick={() => { if (draft) draft.auto_title = !draft.auto_title; }}
           ><i></i></button>
         </div>
       </div>
       <div class="row">
         <div class="lab">名前採用のしきい値</div>
   ```

2. **(gate: type-check)** Run:
   ```
   cd apps/web && npm run check
   ```
   Expected: 0 errors, 0 warnings. (`draft.auto_title` is now a known field on `AudioSettings` from Task CB.1; without that field this would fail `svelte-check` — confirming CB.1 landed first.)

3. **(gate: build)** Run:
   ```
   cd apps/web && npm run build
   ```
   Expected: build succeeds, output to `apps/web/dist/`.

4. **(gate: Playwright visual — controller-run)** The controller runs the Playwright visual gate: open Settings → 音声・録音 → 話者分離 / 名前予想 group; confirm the new 「録音タイトルの自動命名」 switch renders aligned with the existing switches, toggles on click (track color flips, knob slides), and that Save persists (reload → still reflects the chosen state). Capture a screenshot of the group as the visual-regression artifact. GUI change is NOT considered PASS on `npm run check`/`build` green alone — the screenshot gate is mandatory.

5. **(commit)**
   ```
   git add apps/web/src/lib/components/settings/AudioSettingsSection.svelte
   git commit -m "feat(settings): 録音タイトル自動命名トグルを音声設定に追加"

---

## c-2 Inline source rename (all source kinds)

> Depends on (c-1) for `core/storage/sources_repo.update_source_title`. As of the current file read, `sources_repo.py` does **NOT** yet contain `update_source_title` (latest function is `upsert_dedupe`). Task CR.1 below adds it **only if (c-1) has not already merged it**. If (c-1) has landed by the time CR.1 runs, skip CR.1's impl step (the failing test will already pass) and proceed straight to its commit/verification.
>
> **Spec-vs-code discrepancy (resolved in favor of the codebase):** the design spec says empty/whitespace title returns **422**. The actual `AppError` → HTTP mapping in `apps/api/main.py` maps `input.invalid` → **400**. To stay consistent with every other endpoint in this app (e.g. `test_retry_source_missing_bytes_returns_400`), this sub-feature raises `AppError(ErrorCode.INPUT_INVALID, ...)` which yields **HTTP 400** with body `error.code == "input.invalid"`. Tests assert 400. (Changing the global map to 422 is out of scope and would break existing tests.)

---

### Task CR.1 — `update_source_title` repo helper (guarded; may already exist via c-1)

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\core\storage\sources_repo.py`
- Test: `E:\00_Git\10_NotebookOllama\tests\integration\test_storage\test_sources_repo_update_title.py` (Create)

**Interfaces**
- Produces: `update_source_title(conn: sqlite3.Connection, source_id: str, title: str) -> SourceRecord` — runs `UPDATE sources SET title=?, updated_at=? WHERE id=?` then returns `get_source(conn, source_id)`. Raises `AppError(STORAGE_NOT_FOUND)` (via `get_source`) for an unknown id.
- Consumes: existing `get_source`, `_now`, `SourceRecord` in the same module.

**Steps**

1. **Failing test.** Create `tests\integration\test_storage\test_sources_repo_update_title.py`:

```python
import sqlite3

import pytest

from core.exceptions import AppError, ErrorCode
from core.storage import sources_repo
from core.storage.database import migrate


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    migrate(c)
    return c


def _nb(conn: sqlite3.Connection) -> str:
    from core.storage import notebooks_repo

    return notebooks_repo.create_notebook(conn, name="N").id


def test_update_source_title_sets_title_and_bumps_updated_at(conn):
    nb = _nb(conn)
    src = sources_repo.create_source(conn, notebook_id=nb, kind="recording", origin="録音")
    assert src.title is None

    updated = sources_repo.update_source_title(conn, src.id, "週次定例 RAG 改善")
    assert updated.title == "週次定例 RAG 改善"
    assert updated.id == src.id
    assert updated.updated_at >= src.updated_at


def test_update_source_title_unknown_id_raises_not_found(conn):
    with pytest.raises(AppError) as ei:
        sources_repo.update_source_title(conn, "does-not-exist", "x")
    assert ei.value.code == ErrorCode.STORAGE_NOT_FOUND
```

2. **Run-fail.** `cd E:\00_Git\10_NotebookOllama && uv run pytest tests/integration/test_storage/test_sources_repo_update_title.py -q`
   Expected: collection passes, both tests **FAIL** with `AttributeError: module 'core.storage.sources_repo' has no attribute 'update_source_title'` (unless c-1 already added it, in which case both PASS — then skip step 3).

3. **Minimal impl** (only if step 2 failed). In `core\storage\sources_repo.py`, add immediately after `update_source_status` (after its closing `return get_source(conn, source_id)` on line 130, before `def upsert_dedupe`):

```python
def update_source_title(
    conn: sqlite3.Connection,
    source_id: str,
    title: str,
) -> SourceRecord:
    get_source(conn, source_id)  # raises STORAGE_NOT_FOUND if absent
    conn.execute(
        "UPDATE sources SET title=?, updated_at=? WHERE id=?",
        (title, _now(), source_id),
    )
    return get_source(conn, source_id)
```

4. **Run-pass.** `cd E:\00_Git\10_NotebookOllama && uv run pytest tests/integration/test_storage/test_sources_repo_update_title.py -q`
   Expected: `2 passed`.

5. **Commit.**
   `git add core/storage/sources_repo.py tests/integration/test_storage/test_sources_repo_update_title.py`
   `git commit -m "feat(sources): update_source_title リポジトリ関数を追加"`
   (If c-1 already provided the function, `core/storage/sources_repo.py` will be unchanged — then `git add tests/integration/test_storage/test_sources_repo_update_title.py` only, message: `test(sources): update_source_title の回帰テストを追加`.)

---

### Task CR.2 — `PATCH /{notebook_id}/sources/{source_id}` rename endpoint + `SourceRename` schema

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\apps\api\schemas\source.py`
- Modify: `E:\00_Git\10_NotebookOllama\apps\api\routers\sources.py`
- Test: `E:\00_Git\10_NotebookOllama\tests\integration\test_api\test_sources_rename.py` (Create)

**Interfaces**
- Produces (HTTP): `PATCH /api/notebooks/{notebook_id}/sources/{source_id}`, request body `SourceRename {title: str}`, response `Source` (200). Ownership mismatch → `AppError(STORAGE_NOT_FOUND)` → 404. Empty/whitespace-only title → `AppError(INPUT_INVALID)` → 400, body `error.code == "input.invalid"`.
- Produces (schema): `class SourceRename(BaseModel): title: str` in `apps/api/schemas/source.py`.
- Consumes: `sources_repo.get_source`, `sources_repo.update_source_title` (Task CR.1), `_to_schema(rec, sources_dir)`, `ctx.config.sources_dir`.

**Steps**

1. **Failing test.** Create `tests\integration\test_api\test_sources_rename.py` (mirrors `test_sources_api.py` fixture and `test_recording_stop_dispatch.py` conventions):

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


def _create_nb(client, name="N") -> str:
    r = client.post("/api/notebooks", json={"name": name})
    return r.json()["id"]


def _upload_doc(client, nb) -> str:
    files = {"file": ("hello.md", io.BytesIO(b"# Hello\n\nbody."), "text/markdown")}
    r = client.post(f"/api/notebooks/{nb}/sources", files=files)
    assert r.status_code == 202, r.text
    return r.json()["id"]


def _create_recording(client, nb) -> str:
    from core.storage import sources_repo

    ctx = client.app.state.ctx
    src = sources_repo.create_source(
        ctx.conn, notebook_id=nb, kind="recording", title=None, origin="録音"
    )
    return src.id


def test_rename_recording_returns_updated_title(client):
    nb = _create_nb(client)
    sid = _create_recording(client, nb)
    r = client.patch(
        f"/api/notebooks/{nb}/sources/{sid}", json={"title": "週次定例 RAG 改善"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == sid
    assert body["title"] == "週次定例 RAG 改善"
    # persisted: a fresh GET reflects the new title.
    listed = client.get(f"/api/notebooks/{nb}/sources").json()
    assert any(s["id"] == sid and s["title"] == "週次定例 RAG 改善" for s in listed)


def test_rename_document_source(client):
    nb = _create_nb(client)
    sid = _upload_doc(client, nb)
    r = client.patch(
        f"/api/notebooks/{nb}/sources/{sid}", json={"title": "仕様メモ"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "仕様メモ"


def test_rename_empty_title_returns_400(client):
    nb = _create_nb(client)
    sid = _create_recording(client, nb)
    r = client.patch(f"/api/notebooks/{nb}/sources/{sid}", json={"title": "   "})
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "input.invalid"


def test_rename_cross_notebook_returns_404(client):
    nb_a = _create_nb(client, "A")
    nb_b = _create_nb(client, "B")
    sid = _create_recording(client, nb_a)
    r = client.patch(f"/api/notebooks/{nb_b}/sources/{sid}", json={"title": "x"})
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "storage.not_found"
```

2. **Run-fail.** `cd E:\00_Git\10_NotebookOllama && uv run pytest tests/integration/test_api/test_sources_rename.py -q`
   Expected: all 4 tests **FAIL** — the PATCH route does not exist, so FastAPI returns 405 Method Not Allowed (`assert r.status_code == 200` / `== 400` / `== 404` all fail on the 405).

3. **Impl — schema.** In `apps\api\schemas\source.py`, add after the `SourceUrlCreate` class (currently ends at line 23):

```python


class SourceRename(BaseModel):
    title: str
```

4. **Impl — router.** In `apps\api\routers\sources.py`:

   a. Extend the schema import on line 10 to include `SourceRename`:

```python
from apps.api.schemas.source import Source, SourceRename, SourceUrlCreate
```

   b. Add the PATCH handler immediately after `delete_source` (after its `return Response(status_code=204)` on line 212, before `get_chunk`):

```python
@router.patch("/{notebook_id}/sources/{source_id}", response_model=Source)
async def rename_source(
    request: Request,
    notebook_id: str,
    source_id: str,
    body: SourceRename,
) -> Source:
    ctx = request.app.state.ctx
    src = sources_repo.get_source(ctx.conn, source_id)
    if src.notebook_id != notebook_id:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "source not in notebook")
    title = body.title.strip()
    if not title:
        raise AppError(ErrorCode.INPUT_INVALID, "title must not be empty")
    sources_repo.update_source_title(ctx.conn, source_id, title)
    return _to_schema(
        sources_repo.get_source(ctx.conn, source_id), ctx.config.sources_dir
    )
```

5. **Run-pass.** `cd E:\00_Git\10_NotebookOllama && uv run pytest tests/integration/test_api/test_sources_rename.py -q`
   Expected: `4 passed`.

6. **Regression guard.** `cd E:\00_Git\10_NotebookOllama && uv run pytest tests/integration/test_api/test_sources_api.py -q`
   Expected: all existing source-API tests still pass (no behavior change to existing routes).

7. **Commit.**
   `git add apps/api/schemas/source.py apps/api/routers/sources.py tests/integration/test_api/test_sources_rename.py`
   `git commit -m "feat(api): ソース名インライン変更の PATCH エンドポイントを追加"`

---

### Task CR.3 — Frontend API client `sourcesApi.rename`

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\api\sources.ts`

**Interfaces**
- Produces: `sourcesApi.rename(notebookId: string, sourceId: string, title: string) => Promise<Source>` — `PATCH /api/notebooks/{notebookId}/sources/{sourceId}` with JSON body `{ title }`; resolves to the updated `Source`.
- Consumes: existing `request<T>` and `Source` type already imported in this file.

**Steps**

1. **Impl.** In `apps\web\src\lib\api\sources.ts`, add a `rename` method inside the `sourcesApi` object, immediately after the `delete` method (between the `delete` block ending on line 23 and `retry:` on line 24):

```typescript
  rename: (notebookId: string, sourceId: string, title: string) =>
    request<Source>(`/api/notebooks/${notebookId}/sources/${sourceId}`, {
      method: 'PATCH',
      body: JSON.stringify({ title }),
    }),
```

   (The `request` helper auto-sets `Content-Type: application/json` for non-FormData bodies — see `client.ts` lines 35-37 — so no manual header is needed, matching `uploadUrl`.)

2. **Type-check gate.** `cd E:\00_Git\10_NotebookOllama\apps\web && npm run check`
   Expected: **0 errors, 0 warnings** (`svelte-check found 0 errors and 0 warnings`).

3. **Commit.**
   `git add apps/web/src/lib/api/sources.ts`
   `git commit -m "feat(web): sourcesApi.rename を追加"`

---

### Task CR.4 — `SourceCard.svelte` inline edit affordance (pencil → input)

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\SourceCard.svelte`

**Interfaces**
- Consumes: new prop `onRename: (id: string, title: string) => void`. The trigger is a dedicated button/input that calls `onRename` and does **not** fire `onSelect` (the title-edit input/pencil are siblings of the `.body` select button; clicking them never reaches `onSelect`; the input commits on Enter/blur, cancels on Esc).
- Produces: emits `onRename(source.id, trimmedValue)` on Enter or blur when the value is non-empty and changed; renders the title as `<input>` while `editing` is true.

**Steps**

1. **Impl — script: add prop + local edit state + handlers.**

   a. Extend the lucide import on line 3 to add `Pencil`:

```svelte
  import { FileText, Globe, Mic, CheckCircle, AlertCircle, RefreshCw, Trash2, Pencil } from '@lucide/svelte';
```

   b. Add `onRename` to the `Props` interface (after `onDelete: () => void;` on line 14):

```svelte
    onDelete: () => void;
    onRename: (id: string, title: string) => void;
```

   c. Add `onRename` to the destructure on line 16:

```svelte
  let { source, selected, onToggle, onSelect, onRetry, onReembed, onDelete, onRename }: Props = $props();
```

   d. Add edit state + handlers immediately after the `canReembed` `$derived` block (after its closing `);` on line 59, before the closing `</script>` on line 60):

```svelte

  // インライン題名編集。鉛筆クリックで editing=true、Enter/blur で確定、Esc で取消。
  // 確定値が空 or 変更なしなら API を呼ばない (no-op)。
  let editing = $state(false);
  let editValue = $state('');

  const currentTitle = $derived(source.title ?? source.origin ?? '無題');

  function startEdit(e: MouseEvent) {
    e.stopPropagation();
    editValue = source.title ?? '';
    editing = true;
  }

  function commitEdit() {
    if (!editing) return;
    editing = false;
    const next = editValue.trim();
    if (!next || next === (source.title ?? '')) return;
    onRename(source.id, next);
  }

  function cancelEdit() {
    editing = false;
  }

  function onEditKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault();
      commitEdit();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cancelEdit();
    }
  }
```

2. **Impl — markup: conditional input + pencil button.**

   a. Replace the title `<span>` (line 76) so it swaps to an input while editing. The `.row` block currently is:

```svelte
    <div class="row">
      {#if (KIND_ICON[source.kind] ?? FileText)}
        {@const Icon = KIND_ICON[source.kind] ?? FileText}
        <Icon size="14" />
      {/if}
      <span class="title">{source.title ?? source.origin ?? '無題'}</span>
    </div>
```

   Note `.row` sits **inside** the `<button class="body" onclick={onSelect}>`. Because an `<input>` cannot be a descendant of a `<button>` (invalid HTML and would still bubble clicks), move the editable title OUT of the select button: split the title row out of `.body`. Replace the whole `<button class="body">…</button>` block (lines 70-94) with:

```svelte
  <div class="body-wrap">
    <div class="row">
      {#if (KIND_ICON[source.kind] ?? FileText)}
        {@const Icon = KIND_ICON[source.kind] ?? FileText}
        <Icon size="14" />
      {/if}
      {#if editing}
        <!-- svelte-ignore a11y_autofocus -->
        <input
          class="title-edit"
          type="text"
          bind:value={editValue}
          onkeydown={onEditKeydown}
          onblur={commitEdit}
          onclick={(e) => e.stopPropagation()}
          autofocus
          aria-label="ソース名を編集"
        />
      {:else}
        <button class="title-btn" onclick={onSelect}>
          <span class="title">{currentTitle}</span>
        </button>
        <button
          class="icon edit"
          onclick={startEdit}
          aria-label="名前を編集"
          title="名前を編集"
        >
          <Pencil size="12" />
        </button>
      {/if}
    </div>
    <button class="meta-btn" onclick={onSelect}>
      <div class="meta">
        <span class="kind">{source.kind}</span>
        {#if source.page_count}<span>{source.page_count}p</span>{/if}
        {#if durationLabel}<span>{durationLabel}</span>{/if}
        <span class="status">
          {#if source.status === 'ready'}
            <CheckCircle size="12" color="var(--color-success)" /> ready
          {:else if source.status === 'error'}
            <AlertCircle size="12" color="var(--color-error)" /> {source.error_msg ?? 'error'}
          {:else if source.status === 'embedding' && source.chunk_count}
            <Spinner size={12} /> embedding ({source.embedded ?? 0}/{source.chunk_count})
          {:else}
            <Spinner size={12} /> {source.status}
          {/if}
        </span>
      </div>
    </button>
  </div>
```

   (Rationale: the original single `.body` button wrapped both title and meta; here title and meta each get their own select-button so `onSelect` still fires on a normal card click, while the pencil/input are separate siblings that `stopPropagation` and never select. This keeps the grid `auto 1fr auto` layout: checkbox / body-wrap / actions.)

3. **Impl — styles.** In the `<style>` block, replace the existing `.body` rule (lines 131-137) with rules for the new wrappers and edit affordances. Replace:

```svelte
  .body {
    background: none;
    border: none;
    text-align: left;
    padding: 0;
    overflow: hidden;
  }
```

   with:

```svelte
  .body-wrap {
    min-width: 0;
    overflow: hidden;
  }
  .title-btn,
  .meta-btn {
    background: none;
    border: none;
    text-align: left;
    padding: 0;
    overflow: hidden;
    display: block;
    width: 100%;
    cursor: pointer;
  }
  .title-btn {
    min-width: 0;
    flex: 1;
  }
  .title-edit {
    flex: 1;
    min-width: 0;
    font-size: 13px;
    font-weight: 500;
    border: 1px solid var(--color-accent);
    border-radius: var(--radius-sm);
    padding: 1px var(--space-1);
  }
  .icon.edit {
    opacity: 0;
    flex: none;
  }
  .card:hover .icon.edit {
    opacity: 1;
  }
```

   (The `.icon` base rule on lines 174-181 already styles padding/color/hover; `.icon.edit` only adds the hover-reveal. `.title` / `.row` / `.meta` rules are unchanged.)

4. **Type-check gate.** `cd E:\00_Git\10_NotebookOllama\apps\web && npm run check`
   Expected: **0 errors, 0 warnings**. (If `npm run check` flags `onRename` as a missing prop on the `<SourceCard>` callsite in `SourcesPanel.svelte`, that is fixed in Task CR.5 — run CR.5 before re-asserting a clean tree; CR.4's own component compiles standalone, but the panel callsite will report the missing required prop. To keep CR.4 green in isolation, make `onRename` required here and wire the callsite in CR.5; commit CR.4 and CR.5 together if the check must be clean at commit time — see CR.5 step 3.)

5. **Commit.**
   `git add apps/web/src/lib/components/SourceCard.svelte`
   `git commit -m "feat(web): SourceCard に鉛筆アイコンとインライン名編集を追加"`

---

### Task CR.5 — `SourcesPanel.svelte` `onRename` handler + wiring

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\SourcesPanel.svelte`

**Interfaces**
- Produces: `onRename(s: Source, title: string)` handler → `sourcesApi.rename(notebookId, s.id, title)` → `currentNotebookStore.upsertSource(updated)` + success toast; on error, error toast. Passed to `<SourceCard onRename={(id, title) => onRename(s, title)} />`.
- Consumes: `sourcesApi.rename` (Task CR.3), `currentNotebookStore.upsertSource`, `pushToast` (all already imported in this file).

**Steps**

1. **Impl — handler.** In `apps\web\src\lib\components\SourcesPanel.svelte`, add the handler immediately after `onDelete` (after its closing `}` on line 134, before `</script>` on line 135):

```svelte

  async function onRename(s: Source, title: string) {
    try {
      const updated = await sourcesApi.rename(notebookId, s.id, title);
      currentNotebookStore.upsertSource(updated);
      pushToast('名前を変更しました', 'success');
    } catch (e) {
      pushToast(e instanceof Error ? e.message : String(e), 'error');
    }
  }
```

2. **Impl — wire the prop.** In the `<SourceCard>` callsite (lines 170-178), add the `onRename` prop after `onDelete` (after `onDelete={() => onDelete(s)}` on line 177):

```svelte
        onDelete={() => onDelete(s)}
        onRename={(id, title) => onRename(s, title)}
```

3. **Type-check + build gate.** `cd E:\00_Git\10_NotebookOllama\apps\web && npm run check && npm run build`
   Expected: `svelte-check found 0 errors and 0 warnings`, then a successful Vite build (output to `apps/web/dist/`, exit 0). This is the first point where the full SourceCard↔SourcesPanel wiring type-checks; CR.4's required `onRename` prop is now satisfied here.

4. **Commit.**
   `git add apps/web/src/lib/components/SourcesPanel.svelte`
   `git commit -m "feat(web): SourcesPanel に rename ハンドラを配線"`

5. **Playwright visual gate (controller runs; not a commit step).** With API on `:8765` and `cd apps/web && npm run dev`, verify in a real browser:
   - In a notebook with at least one **recording** source and one **document** (e.g. `.md`) source: hovering a source card reveals the pencil icon next to the title.
   - Clicking the pencil swaps the title to an inline `<input>` pre-filled with the current title; it does **not** open the source viewer (no `onSelect`).
   - Typing a new name and pressing **Enter** (or blurring) updates the card title in place and shows a success toast; pressing **Esc** mid-edit reverts with no change.
   - The rename **persists across reload** (reload the page → the card still shows the new name; confirms the PATCH wrote to SQLite).
   - The same flow works for the **document** source (rename is not recording-only).
   - Screenshot evidence required per repo policy (auto-test GREEN alone does not satisfy the visual gate): capture (1) hover-revealed pencil, (2) inline input mid-edit, (3) renamed card after reload.

---

**Relevant absolute paths**
- Spec: `E:\00_Git\10_NotebookOllama\docs\specs\2026-06-19-recording-naming-design.md`
- Backend: `E:\00_Git\10_NotebookOllama\apps\api\routers\sources.py`, `E:\00_Git\10_NotebookOllama\apps\api\schemas\source.py`, `E:\00_Git\10_NotebookOllama\core\storage\sources_repo.py`
- Frontend: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\api\sources.ts`, `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\SourceCard.svelte`, `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\SourcesPanel.svelte`
- New tests: `E:\00_Git\10_NotebookOllama\tests\integration\test_storage\test_sources_repo_update_title.py`, `E:\00_Git\10_NotebookOllama\tests\integration\test_api\test_sources_rename.py`

**Two load-bearing facts the controller must know:** (1) `update_source_title` did not exist in `sources_repo.py` at read time — CR.1 is its real home unless (c-1) lands first; (2) the spec's "422" for empty title is **wrong for this codebase** — `input.invalid` maps to HTTP **400** in `apps/api/main.py`, so the endpoint and tests use 400.

---

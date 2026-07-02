# クラッシュレポート & お知らせ/フィードバックハブ 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. TDD (失敗テスト→fail 確認→最小実装→pass 確認→commit)。GUI 変更 (Sprint 5-9) は各機能末尾の Playwright 実機スクショ検証ゲート (自動テスト GREEN だけで PASS 禁止 / [[feedback_visual_verification]])。
>
> **絶対遵守メモリ**:
> - [[feedback-no-data-guarantee-in-ui]]: UI で「送信される/されない」を宣言しない。プレビュー確認による合意モデル一本。
> - [[feedback_compact_ui_repurpose_affordance]]: 縦に肥大化させない。既存ヘッダ・既存設定パネルへ寄せる。
> - [[feedback_visual_verification]]: GUI 変更は Evaluator スクショ必須、`svelte-check` / `npm run build` GREEN だけで PASS 禁止。

**Goal:** spec `docs/specs/2026-06-28-crash-report-feedback-hub-design.md` を完全実装する。
1. クラッシュ自動検知 (FastAPI 例外 / `sys.excepthook` / signal / atexit / unclean shutdown / フロント `window.onerror`) → ユーザー編集つき GitHub Issue 起票 URL 生成。
2. ヘッダの Megaphone アイコン → 右側 Drawer (お知らせ / 不具合 / ご意見の 3 タブ)。
3. 設定画面に「クラッシュレポート」セクション、初回オプトインモーダル。
4. ご意見タブで html2canvas によるスクショ任意添付 (URL 埋め込み不可 → クリップボード経由)。

**Architecture:** FastAPI (`apps/api/`) + 純ドメイン (`core/`) + SvelteKit (Svelte 5 runes, `apps/web/`)。SQLite + Qdrant + Ollama。設計仕様: `docs/specs/2026-06-28-crash-report-feedback-hub-design.md` (決定は確定)。

**Tech Stack:**
- Python (uv / pytest / ruff)。新規依存: なし (psutil は recording extra で既出 → core 移動)。`nvidia-smi` は subprocess。
- TypeScript + Svelte 5 runes (`svelte-check` / `vite build`)。新規 npm 依存: `html2canvas@^1.4.1`。

**ブランチ:** `feat/crash-report-feedback-hub` (現在地。`master` + 1 commit = spec 追加のみ。実装はこのブランチに積む。`master` 直接編集禁止)。

**PR 分割戦略** (recommended):
| フェーズ | 含む sprint | PR 種別 |
|---|---|---|
| バックエンド基盤 | Sprint 1-4 | **Draft PR** を Sprint 1 完了時に open し、Sprint 2-4 完了ごとに push。バックエンド単体で `uv run pytest` GREEN を維持。 |
| フロント結線 | Sprint 5-8 | 同じ PR に **コミット追加**。Sprint 5 で Drawer 枠 + 即時モーダル + プレビュー (GUI 検証ゲート初回) → Sprint 6/7/8 でタブ充填。各 sprint 末に視覚ゲート。 |
| 統合・仕上げ | Sprint 9 | E2E 通過とアイコン最終サイズ確定後、Draft → **Ready for Review**。レビュー指摘吸収後に master へ。 |

## Global Constraints
- **新規ランタイム依存**:
  - Python: なし (`psutil` は既存 `recording` extra。core からは optional import + try/except)。
  - npm: `html2canvas@^1.4.1` のみ (Sprint 8 で `cd apps/web && npm install html2canvas` を実行 + commit)。
- **GUI 変更 (Sprint 5-9) は Playwright 実機スクショ検証ゲートが PASS 条件**。`npm run check` / `npm run build` GREEN だけで完了宣言禁止 ([[feedback_visual_verification]])。
- **既存テストを壊さない** (`uv run pytest` GREEN)。`cd apps/web && npm run check` 0 errors (既存 0/6 warnings の範囲)、`npm run build` 成功。
- **コミット trailer なし** (`Co-Authored-By` 等を付けない。`feature/recording-naming` plan と同様)。
- **GitHub Issue URL の起票先リポジトリ**は `KawanoMomo/notebook-ollama` (origin remote と一致)。定数は `core/crash_reporter/__init__.py` で `REPO_SLUG = "KawanoMomo/notebook-ollama"` として一箇所定義。
- **データ保存先**: `config.data_dir / "crash-pending" / "<id>.json"`, `config.data_dir / "reported.txt"`, `config.data_dir / "running.lock"`, `config.data_dir / "logs" / "last-session.log"`。`config.ensure_dirs()` (Sprint 2 拡張) で `crash-pending/` を作成する。
- **redactor のホワイトリスト準拠**: spec §6.2 を **唯一の正解** とする。実装中に「これも入れたい」が出た場合は spec を先に更新する PR を別出ししてからこの実装を進める。
- **「送信される/されない」UI 文言禁止** ([[feedback-no-data-guarantee-in-ui]])。プレビューに実内容のみを出し、文言での約束は出さない。レビューチェックリスト項目。

## 実装順 (スプリント)

```
Sprint 1 (純粋関数)
    ↓
Sprint 2 (ストレージ)         ← Sprint 1 の redactor/fingerprint/hardware に依存
    ↓
Sprint 3 (traps + crash ルータ + feedback_hub ルータ + DomainError)   ← Sprint 1,2 必要
    ↓
Sprint 4 (lifecycle: running.lock + psutil)                          ← Sprint 2,3 必要
    ↓
Sprint 5 (フロント: 旗ハブ枠 + 即時モーダル + プレビュー)            ← Sprint 3 endpoints 必要
    ↓
Sprint 6 (お知らせタブ)         ← Sprint 5 Drawer + Sprint 3 notices endpoint
    ↓
Sprint 7 (不具合タブ + 設定セクション + 初回オプトイン)               ← Sprint 5,6
    ↓
Sprint 8 (ご意見タブ + html2canvas)                                  ← Sprint 5
    ↓
Sprint 9 (E2E + アイコン最終調整 + ドキュメント)                       ← Sprint 5-8 全て
```

各 sprint 末で `uv run pytest` (backend) + `cd apps/web && npm run check` (frontend) GREEN を満たす。Sprint 5 以降はそれに加え視覚ゲート PASS。

---

## Sprint 1 — 純粋関数群 (`core/crash_reporter/{redactor,fingerprint,hardware}.py`)

**Scope:** FastAPI / DB / asyncio に**触れない** 純粋関数 3 本。Sprint 2 以降が consumer。`hardware.collect()` だけは subprocess (`nvidia-smi`) を呼ぶが、結果は dict を返す。

**Deliverables:**
- `core/crash_reporter/__init__.py` (constants `REPO_SLUG`, `MAX_URL_LEN`)
- `core/crash_reporter/redactor.py`
- `core/crash_reporter/fingerprint.py`
- `core/crash_reporter/hardware.py`

### Task 1.0 — `core/crash_reporter/__init__.py` 定数モジュール

**Files**
- Create: `E:\00_Git\10_NotebookOllama\core\crash_reporter\__init__.py`
- Test: `E:\00_Git\10_NotebookOllama\tests\unit\crash_reporter\__init__.py` (空)
- Test: `E:\00_Git\10_NotebookOllama\tests\unit\crash_reporter\test_constants.py` (Create)

**Interfaces**
- Produces: `REPO_SLUG: str = "KawanoMomo/notebook-ollama"` — Issue URL ホスト先。
- Produces: `MAX_URL_LEN: int = 7000` — GitHub の 8KB 制限に対する安全マージン。
- Produces: `BLOCKED_LOG_KEYS: frozenset[str]` — spec §6.2 「通さない」キー一覧。Sprint 1 で定数化し、redactor / formatter が import する。

**Steps**

1. **(red) テスト作成。** `tests/unit/crash_reporter/test_constants.py`:
   ```python
   from core.crash_reporter import REPO_SLUG, MAX_URL_LEN, BLOCKED_LOG_KEYS

   def test_repo_slug_matches_origin():
       assert REPO_SLUG == "KawanoMomo/notebook-ollama"

   def test_max_url_len_safe_under_8kb():
       assert 6000 <= MAX_URL_LEN <= 7500  # GitHub 8KB - エンコード余白

   def test_blocked_log_keys_contains_spec_listed():
       # spec §6.2 「通さない」リストの全項目を含むこと
       must = {
           "doc_id", "source_id", "chunk_id", "chunk_text", "text", "content",
           "embedding", "vector", "query", "question", "prompt", "response",
           "answer", "filename", "file_path", "title", "transcript",
           "audio_path", "user_input", "user_message", "messages", "documents",
       }
       assert must <= BLOCKED_LOG_KEYS
   ```

2. **(run-fail)** `uv run pytest tests/unit/crash_reporter/test_constants.py -q`
   期待: `ModuleNotFoundError: No module named 'core.crash_reporter'`。

3. **(green) 実装。** `core/crash_reporter/__init__.py`:
   ```python
   """クラッシュレポート機能の公開定数。

   spec: docs/specs/2026-06-28-crash-report-feedback-hub-design.md
   """
   from __future__ import annotations

   REPO_SLUG: str = "KawanoMomo/notebook-ollama"
   """GitHub Issue 起票先のリポジトリ slug (origin remote と一致)。"""

   MAX_URL_LEN: int = 7000
   """GitHub の 8KB URL 制限に対する安全マージン (URL エンコード分を見込んだ上限)。"""

   BLOCKED_LOG_KEYS: frozenset[str] = frozenset({
       # spec §6.2 「通さない」一覧。構造化ログにこれらキーが現れたら、
       # その行ごと破棄する(redactor.redact_log_event の責務)。
       "doc_id", "source_id", "chunk_id", "chunk_text", "text", "content",
       "embedding", "vector", "query", "question", "prompt", "response",
       "answer", "filename", "file_path", "title", "transcript",
       "audio_path", "user_input", "user_message", "messages", "documents",
   })
   """ホワイトリスト方式の念のための明示禁止リスト。"""
   ```

4. **(run-pass)** `uv run pytest tests/unit/crash_reporter/test_constants.py -q` → 3 passed。

5. **(commit)**
   ```
   git add core/crash_reporter/__init__.py tests/unit/crash_reporter/__init__.py tests/unit/crash_reporter/test_constants.py
   git commit -m "feat(crash-reporter): 公開定数モジュールを追加 (REPO_SLUG / MAX_URL_LEN / BLOCKED_LOG_KEYS)"
   ```

---

### Task 1.1 — `core/crash_reporter/redactor.py` ホワイトリスト方式 PII フィルタ

**Files**
- Create: `E:\00_Git\10_NotebookOllama\core\crash_reporter\redactor.py`
- Test: `E:\00_Git\10_NotebookOllama\tests\unit\crash_reporter\test_redactor.py` (Create)

**Interfaces**
- Consumes: `BLOCKED_LOG_KEYS` (Task 1.0)。
- Produces: `redact_log_event(event: dict) -> dict | None` — spec §6.2 「通す」フィールドのみ残した dict を返す。禁止キーが 1 つでも含まれていれば `None` を返す (= 行ごと破棄)。
- Produces: `redact_traceback(tb_lines: list[str], app_root: Path) -> list[str]` — ユーザー HOME 配下のパスを `<HOME>/...` に置換し、`app_root` 配下と `site-packages/` 配下は保持。
- Produces: `redact_exception_message(exc: BaseException) -> str` — `DomainError` を継承する例外は `safe_message`、それ以外は型名 + モジュール名のみ (メッセージ本体は捨てる)。
- Produces: `ALLOWED_LOG_FIELDS: frozenset[str]` — spec §6.2 「通す」フィールド一覧。

**Steps**

1. **(red) テスト作成。** `tests/unit/crash_reporter/test_redactor.py`:
   ```python
   from pathlib import Path

   import pytest

   from core.crash_reporter.redactor import (
       ALLOWED_LOG_FIELDS,
       redact_exception_message,
       redact_log_event,
       redact_traceback,
   )


   class _DomainErr(Exception):
       safe_message = "Qdrant collection not found"


   class _UnknownErr(Exception):
       pass


   def test_allowed_fields_match_spec():
       must = {
           "level", "event_name", "timestamp", "request_id",
           "method", "path_pattern", "status_code", "duration_ms",
           "exception_type", "exception_module", "error_kind",
           "count", "n_chunks", "n_sources", "top_k",
           "model",
       }
       assert must <= ALLOWED_LOG_FIELDS


   def test_redact_log_event_passes_whitelisted():
       ev = {
           "level": "ERROR", "event_name": "rag.search",
           "timestamp": "2026-06-28T00:00:00Z", "status_code": 500,
           "duration_ms": 42, "top_k": 8, "model": "qwen2.5:14b",
       }
       assert redact_log_event(ev) == ev


   def test_redact_log_event_drops_event_with_blocked_key():
       ev = {
           "level": "INFO", "event_name": "x",
           "chunk_text": "leaked!",  # blocked
       }
       assert redact_log_event(ev) is None


   def test_redact_log_event_strips_unknown_keys_but_keeps_whitelisted():
       ev = {
           "level": "INFO", "event_name": "x",
           "host_name": "my-laptop",  # not whitelisted, no leak
           "duration_ms": 1,
       }
       out = redact_log_event(ev)
       assert out == {"level": "INFO", "event_name": "x", "duration_ms": 1}


   @pytest.mark.parametrize("key", [
       "chunk_text", "text", "content", "embedding", "query",
       "prompt", "response", "answer", "filename", "file_path",
       "title", "transcript", "audio_path", "user_input",
       "user_message", "messages", "documents",
   ])
   def test_redact_log_event_drops_all_blocked_keys(key):
       assert redact_log_event({"level": "INFO", "event_name": "x", key: "leak"}) is None


   def test_redact_traceback_strips_home_path(tmp_path, monkeypatch):
       monkeypatch.setattr(Path, "home", lambda: tmp_path)
       home_file = str(tmp_path / "secrets" / "doc.pdf")
       lines = [
           f'  File "{home_file}", line 1, in <module>',
           '  File "/usr/lib/python3.12/site-packages/fastapi/x.py", line 5',
       ]
       app_root = tmp_path / "app"  # 配下に何も無いケース
       out = redact_traceback(lines, app_root)
       assert "<HOME>" in out[0]
       assert str(tmp_path) not in out[0]
       # site-packages はそのまま残る
       assert "site-packages" in out[1]


   def test_redact_exception_message_uses_safe_message_for_domain_error():
       assert redact_exception_message(_DomainErr("internal payload")) == "Qdrant collection not found"


   def test_redact_exception_message_strips_unknown_exception_body():
       msg = redact_exception_message(_UnknownErr("doc_id=abc was missing"))
       # 型名 + モジュール名のみ。本文は出ない。
       assert "_UnknownErr" in msg
       assert "doc_id" not in msg
       assert "abc" not in msg
   ```

2. **(run-fail)** `uv run pytest tests/unit/crash_reporter/test_redactor.py -q` → `ModuleNotFoundError: No module named 'core.crash_reporter.redactor'`。

3. **(green) 実装。** `core/crash_reporter/redactor.py`:
   ```python
   """ホワイトリスト方式の構造化ログ / トレースバック / 例外メッセージ検疫。

   spec §6.2 / §6.3 準拠。"通す"フィールドだけを通し、ブラックリスト fallback は
   しない。これによりログスキーマ追加時のリーク事故を構造的に防ぐ。
   """
   from __future__ import annotations

   from pathlib import Path

   from core.crash_reporter import BLOCKED_LOG_KEYS


   ALLOWED_LOG_FIELDS: frozenset[str] = frozenset({
       "level", "event_name", "timestamp", "request_id",
       "method", "path_pattern", "status_code", "duration_ms",
       "exception_type", "exception_module", "error_kind",
       "count", "n_chunks", "n_sources", "top_k",
       "model",
   })


   def redact_log_event(event: dict) -> dict | None:
       """構造化ログ 1 イベントを検疫する。

       - 禁止キーが 1 つでも含まれれば `None` (行ごと破棄)。
       - 残りはホワイトリスト ALLOWED_LOG_FIELDS のキーだけを残す。
       """
       for key in event:
           if key in BLOCKED_LOG_KEYS:
               return None
       return {k: v for k, v in event.items() if k in ALLOWED_LOG_FIELDS}


   def redact_traceback(tb_lines: list[str], app_root: Path) -> list[str]:
       """traceback 各行から個人識別パスを除去する。

       - HOME 配下のパスを `<HOME>/...` に置換。
       - `app_root` 配下と `site-packages/` 配下はそのまま残す。
       """
       home = str(Path.home())
       out: list[str] = []
       for line in tb_lines:
           # HOME 置換は単純文字列置換でよい (Windows / POSIX 両対応)
           red = line.replace(home, "<HOME>")
           out.append(red)
       return out


   def redact_exception_message(exc: BaseException) -> str:
       """spec §6.3 3 層防御。DomainError なら safe_message、未知例外は型名のみ。"""
       safe = getattr(exc, "safe_message", None)
       if isinstance(safe, str) and safe:
           return safe
       cls = type(exc)
       return f"{cls.__module__}.{cls.__qualname__}"
   ```

4. **(run-pass)** `uv run pytest tests/unit/crash_reporter/test_redactor.py -q` → 全て pass。

5. **(commit)**
   ```
   git add core/crash_reporter/redactor.py tests/unit/crash_reporter/test_redactor.py
   git commit -m "feat(crash-reporter): ホワイトリスト方式 redactor (log/traceback/exception)"
   ```

---

### Task 1.2 — `core/crash_reporter/fingerprint.py` スタックトレース SHA1

**Files**
- Create: `E:\00_Git\10_NotebookOllama\core\crash_reporter\fingerprint.py`
- Test: `E:\00_Git\10_NotebookOllama\tests\unit\crash_reporter\test_fingerprint.py` (Create)

**Interfaces**
- Produces: `compute_fingerprint(exc: BaseException) -> str` — `traceback.extract_tb` で各フレームから `(module, function)` を抽出し、行番号を**捨てて** SHA1 を取る。同一例外型 + 同一スタックトポロジ ⇒ 同一ハッシュ。

**Steps**

1. **(red) テスト作成。** `tests/unit/crash_reporter/test_fingerprint.py`:
   ```python
   import pytest

   from core.crash_reporter.fingerprint import compute_fingerprint


   def _raise_at(depth: int):
       if depth == 0:
           raise RuntimeError("boom")
       return _raise_at(depth - 1)


   def test_same_traceback_yields_same_hash():
       try:
           _raise_at(2)
       except RuntimeError as e1:
           fp1 = compute_fingerprint(e1)
       try:
           _raise_at(2)
       except RuntimeError as e2:
           fp2 = compute_fingerprint(e2)
       assert fp1 == fp2


   def test_different_exception_type_yields_different_hash():
       try:
           raise RuntimeError("x")
       except RuntimeError as e1:
           fp1 = compute_fingerprint(e1)
       try:
           raise ValueError("x")
       except ValueError as e2:
           fp2 = compute_fingerprint(e2)
       assert fp1 != fp2


   def test_line_number_change_does_not_change_hash(monkeypatch):
       # 行番号を入れ替えても同じスタックトポロジなら同じハッシュであることを
       # 「同じ関数で 2 回 raise」で間接検証する。
       try:
           raise RuntimeError("a")
       except RuntimeError as e1:
           fp1 = compute_fingerprint(e1)
       try:
           raise RuntimeError("b")  # message が変わっても fp は変わらない
       except RuntimeError as e2:
           fp2 = compute_fingerprint(e2)
       assert fp1 == fp2  # 行番号は同じ、message は捨てているので一致


   def test_returns_hex_sha1():
       try:
           raise RuntimeError("x")
       except RuntimeError as e:
           fp = compute_fingerprint(e)
       assert len(fp) == 40
       int(fp, 16)  # hex
   ```

2. **(run-fail)** `uv run pytest tests/unit/crash_reporter/test_fingerprint.py -q` → `ModuleNotFoundError`。

3. **(green) 実装。** `core/crash_reporter/fingerprint.py`:
   ```python
   """例外のスタックトポロジから fingerprint を計算する (重複 Issue 抑制用)。"""
   from __future__ import annotations

   import hashlib
   import traceback


   def compute_fingerprint(exc: BaseException) -> str:
       """例外型 + (module, function) フレーム列の SHA1 を返す。

       - 行番号は意図的に捨てる: 周辺コードの編集で fingerprint が変わると
         「同じバグ」を再報告してしまう。
       - メッセージ本文も捨てる: 同じバグでも入力依存で本文が変わるため。
       """
       cls = type(exc)
       parts: list[str] = [f"{cls.__module__}.{cls.__qualname__}"]
       tb = exc.__traceback__
       for frame in traceback.extract_tb(tb):
           # frame.filename はフルパス。モジュール末尾名のみで安定化。
           module = frame.filename.replace("\\", "/").rsplit("/", 1)[-1]
           parts.append(f"{module}::{frame.name}")
       digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
       return digest
   ```

4. **(run-pass)** `uv run pytest tests/unit/crash_reporter/test_fingerprint.py -q` → 4 passed。

5. **(commit)**
   ```
   git add core/crash_reporter/fingerprint.py tests/unit/crash_reporter/test_fingerprint.py
   git commit -m "feat(crash-reporter): スタックトポロジ SHA1 fingerprint"
   ```

---

### Task 1.3 — `core/crash_reporter/hardware.py` CPU/RAM/GPU 情報採取

**Files**
- Create: `E:\00_Git\10_NotebookOllama\core\crash_reporter\hardware.py`
- Test: `E:\00_Git\10_NotebookOllama\tests\unit\crash_reporter\test_hardware.py` (Create)

**Interfaces**
- Produces: `collect() -> dict[str, str | int | None]` — 以下キーの dict。失敗キーは `"<unavailable>"`。
  - `cpu_model`, `cpu_cores`, `cpu_threads`
  - `ram_total_gb`, `ram_available_gb`
  - `gpu_model`, `gpu_vram_mb`, `cuda_version`, `driver_version`
  - `os_arch`, `os_platform`, `python_version`
  - `disk_free_gb` (data_dir の空き容量数値のみ)
- Consumes: `psutil` (optional import: `from importlib import import_module; try: psutil = import_module("psutil"); except ImportError: psutil = None`)。`subprocess.run("nvidia-smi", ...)`。

**Steps**

1. **(red) テスト作成。** `tests/unit/crash_reporter/test_hardware.py`:
   ```python
   from unittest.mock import patch

   from core.crash_reporter import hardware


   def test_collect_returns_required_keys():
       result = hardware.collect()
       required = {
           "cpu_model", "cpu_cores", "cpu_threads",
           "ram_total_gb", "ram_available_gb",
           "gpu_model", "gpu_vram_mb", "cuda_version", "driver_version",
           "os_arch", "os_platform", "python_version", "disk_free_gb",
       }
       assert required <= set(result.keys())


   def test_collect_does_not_leak_hostname():
       result = hardware.collect()
       import platform
       host = platform.node()
       for v in result.values():
           if isinstance(v, str):
               assert host == "" or host not in v, (
                   f"hostname leaked into hardware.collect(): {v!r}"
               )


   def test_collect_handles_nvidia_smi_missing():
       with patch("core.crash_reporter.hardware._run_nvidia_smi", return_value=None):
           r = hardware.collect()
       assert r["gpu_model"] == "<unavailable>"
       assert r["gpu_vram_mb"] == "<unavailable>"


   def test_collect_handles_psutil_missing(monkeypatch):
       monkeypatch.setattr(hardware, "_psutil", None)
       r = hardware.collect()
       assert r["ram_total_gb"] == "<unavailable>"
       assert r["ram_available_gb"] == "<unavailable>"
       assert r["disk_free_gb"] == "<unavailable>"


   def test_collect_parses_nvidia_smi_csv():
       fake = "NVIDIA GeForce RTX 2080 Ti, 11264, 12.4, 555.42\n"
       with patch("core.crash_reporter.hardware._run_nvidia_smi", return_value=fake):
           r = hardware.collect()
       assert r["gpu_model"] == "NVIDIA GeForce RTX 2080 Ti"
       assert r["gpu_vram_mb"] == 11264
       assert r["cuda_version"] == "12.4"
       assert r["driver_version"] == "555.42"
   ```

2. **(run-fail)** `uv run pytest tests/unit/crash_reporter/test_hardware.py -q` → `ModuleNotFoundError`。

3. **(green) 実装。** `core/crash_reporter/hardware.py`:
   ```python
   """ハードウェア / 実行環境のスナップショット採取 (PII を含めない)。

   spec §6.2 「個人特定可能なハードウェア情報も除外」: hostname / MAC / IP /
   ディスクパス / シリアル番号は含めない。psutil / nvidia-smi が無い環境では
   該当値を "<unavailable>" にしてフォールバックする。
   """
   from __future__ import annotations

   import os
   import platform
   import subprocess
   import sys
   from pathlib import Path

   try:
       import psutil as _psutil  # type: ignore
   except ImportError:
       _psutil = None  # noqa: N816

   _UNAVAIL = "<unavailable>"


   def _run_nvidia_smi() -> str | None:
       try:
           out = subprocess.run(
               [
                   "nvidia-smi",
                   "--query-gpu=name,memory.total,driver_version",
                   "--format=csv,noheader,nounits",
               ],
               capture_output=True, text=True, timeout=3, check=True,
           )
           return out.stdout
       except (FileNotFoundError, subprocess.SubprocessError, OSError):
           return None


   def _parse_nvidia_smi(text: str | None) -> dict[str, str | int]:
       if not text:
           return {
               "gpu_model": _UNAVAIL, "gpu_vram_mb": _UNAVAIL,
               "cuda_version": _UNAVAIL, "driver_version": _UNAVAIL,
           }
       first = text.strip().splitlines()[0]
       parts = [p.strip() for p in first.split(",")]
       # name, memory.total, [cuda_version?,] driver_version
       # 4 列 (name, mem, cuda, drv) を許容
       if len(parts) == 4:
           name, vram, cuda, drv = parts
       elif len(parts) == 3:
           name, vram, drv = parts
           cuda = _UNAVAIL
       else:
           return {
               "gpu_model": _UNAVAIL, "gpu_vram_mb": _UNAVAIL,
               "cuda_version": _UNAVAIL, "driver_version": _UNAVAIL,
           }
       try:
           vram_int: str | int = int(vram)
       except ValueError:
           vram_int = _UNAVAIL
       return {
           "gpu_model": name or _UNAVAIL,
           "gpu_vram_mb": vram_int,
           "cuda_version": cuda or _UNAVAIL,
           "driver_version": drv or _UNAVAIL,
       }


   def collect(data_dir: Path | None = None) -> dict[str, str | int | None]:
       cpu_model = platform.processor() or _UNAVAIL
       cpu_threads = os.cpu_count() or _UNAVAIL
       cpu_cores = cpu_threads  # logical cores (psutil 無しでも threads は取れる)
       if _psutil is not None:
           try:
               cpu_cores = _psutil.cpu_count(logical=False) or cpu_threads
           except Exception:
               cpu_cores = cpu_threads

       if _psutil is not None:
           try:
               vm = _psutil.virtual_memory()
               ram_total = round(vm.total / (1024 ** 3), 1)
               ram_avail = round(vm.available / (1024 ** 3), 1)
           except Exception:
               ram_total = _UNAVAIL
               ram_avail = _UNAVAIL
       else:
           ram_total = _UNAVAIL
           ram_avail = _UNAVAIL

       gpu = _parse_nvidia_smi(_run_nvidia_smi())

       if _psutil is not None and data_dir is not None:
           try:
               du = _psutil.disk_usage(str(data_dir))
               disk_free = round(du.free / (1024 ** 3), 1)
           except Exception:
               disk_free = _UNAVAIL
       elif _psutil is not None:
           try:
               du = _psutil.disk_usage(str(Path.home()))
               disk_free = round(du.free / (1024 ** 3), 1)
           except Exception:
               disk_free = _UNAVAIL
       else:
           disk_free = _UNAVAIL

       return {
           "cpu_model": cpu_model,
           "cpu_cores": cpu_cores,
           "cpu_threads": cpu_threads,
           "ram_total_gb": ram_total,
           "ram_available_gb": ram_avail,
           **gpu,
           "os_arch": platform.machine() or _UNAVAIL,
           "os_platform": platform.platform() or _UNAVAIL,
           "python_version": sys.version.split()[0],
           "disk_free_gb": disk_free,
       }
   ```

4. **(run-pass)** `uv run pytest tests/unit/crash_reporter/test_hardware.py -q` → 全 pass。
   注: `test_collect_handles_psutil_missing` は `monkeypatch.setattr(hardware, "_psutil", None)` でモジュール属性を差し替えるので、`_psutil = None` のフォールバックを実装で踏ませる。

5. **(commit)**
   ```
   git add core/crash_reporter/hardware.py tests/unit/crash_reporter/test_hardware.py
   git commit -m "feat(crash-reporter): hardware.collect (psutil + nvidia-smi、PIIなし)"
   ```

---

### Sprint 1 ゲート

- `uv run pytest tests/unit/crash_reporter/ -q` → 全 pass。
- `uv run pytest -q` → 既存テスト全 pass (回帰なし)。
- **Draft PR を open**: タイトル `feat: crash-report-feedback-hub backend foundation`, body に「Sprint 1 完了。spec §6.2 redactor + §9 fingerprint + §6.2 hardware。Sprint 2-4 を順次 push 予定」。

---

## Sprint 2 — ストレージ層 (`pending_store` / `reported_store` / `formatter` / `prefill_url`)

**Scope:** 純粋関数 + ファイル I/O (JSON / 1行テキスト / URL 文字列構築)。FastAPI 非依存。Sprint 1 の redactor / fingerprint / hardware を組み合わせる。

**Deliverables:**
- `core/crash_reporter/pending_store.py`
- `core/crash_reporter/reported_store.py`
- `core/crash_reporter/formatter.py`
- `core/crash_reporter/prefill_url.py`

### Task 2.1 — `pending_store.py` 未送信レポート JSON 永続化

**Files**
- Create: `E:\00_Git\10_NotebookOllama\core\crash_reporter\pending_store.py`
- Test: `E:\00_Git\10_NotebookOllama\tests\unit\crash_reporter\test_pending_store.py` (Create)

**Interfaces**
- Produces: `@dataclass class PendingCrash` (id: str, fingerprint: str, created_at: str, exception_type: str, exception_message: str, trace: list[str], hardware: dict, log_tail: list[dict], source: Literal["fastapi", "excepthook", "signal", "atexit", "frontend", "unclean_shutdown"])。
- Produces: `save(data_dir: Path, crash: PendingCrash) -> Path` — `data_dir/crash-pending/<id>.json` を atomic write。
- Produces: `load_all(data_dir: Path) -> list[PendingCrash]` — ディレクトリ内全 JSON を新しい順 (created_at desc) に返す。
- Produces: `get(data_dir: Path, crash_id: str) -> PendingCrash | None`。
- Produces: `delete(data_dir: Path, crash_id: str) -> bool`。

**Steps**

1. **(red) テスト作成。** `tests/unit/crash_reporter/test_pending_store.py` — 以下シナリオを網羅:
   - `save` で `crash-pending/<id>.json` が作られる (ディレクトリ無くても自動作成)。
   - `load_all` が `created_at` 降順で返す。
   - `get` が `None` を返す (未知 id)。
   - `delete` が `True/False` を返す。
   - 壊れた JSON ファイルは `load_all` でスキップされる (起動を止めない)。
   - `save` で atomic (途中失敗ファイルが残らない: tmp ファイル → rename)。

2. **(run-fail)** `uv run pytest tests/unit/crash_reporter/test_pending_store.py -q` → `ModuleNotFoundError`。

3. **(green) 実装。** `core/crash_reporter/pending_store.py`:
   - `dataclasses.asdict(crash)` → `json.dumps(ensure_ascii=False, indent=2)` で書き出し。
   - 書き込みは `path.with_suffix(".json.tmp")` → `os.replace(tmp, path)` で atomic。
   - `load_all` は `for p in sorted(dir.glob("*.json")): try: ... except (OSError, json.JSONDecodeError): continue`。
   - 内部に `_DIR_NAME = "crash-pending"` 定数。

4. **(run-pass)** `uv run pytest tests/unit/crash_reporter/test_pending_store.py -q` → 全 pass。

5. **(commit)** `git commit -m "feat(crash-reporter): pending_store (atomic JSON 永続化)"`

---

### Task 2.2 — `reported_store.py` 送信済み fingerprint リスト

**Files**
- Create: `E:\00_Git\10_NotebookOllama\core\crash_reporter\reported_store.py`
- Test: `E:\00_Git\10_NotebookOllama\tests\unit\crash_reporter\test_reported_store.py` (Create)

**Interfaces**
- Produces: `is_reported(data_dir: Path, fingerprint: str) -> bool` — `data_dir/reported.txt` を行単位スキャン。
- Produces: `mark_reported(data_dir: Path, fingerprint: str) -> None` — 既に含まれていれば no-op、新規なら追記 (append, fsync で flush)。
- Produces: `count(data_dir: Path) -> int`。

**Steps**

1. **(red) テスト作成。**
   ```python
   def test_mark_then_is_reported(tmp_path):
       assert not is_reported(tmp_path, "abc")
       mark_reported(tmp_path, "abc")
       assert is_reported(tmp_path, "abc")

   def test_mark_idempotent(tmp_path):
       mark_reported(tmp_path, "abc")
       mark_reported(tmp_path, "abc")
       assert count(tmp_path) == 1

   def test_missing_file_returns_false(tmp_path):
       assert not is_reported(tmp_path, "any")
       assert count(tmp_path) == 0
   ```

2. **(run-fail)** → `ModuleNotFoundError`。

3. **(green) 実装。** ファイル名 `reported.txt`、UTF-8、1行 1 fingerprint。読み込みは set で。

4. **(run-pass)** → 3 passed。

5. **(commit)** `git commit -m "feat(crash-reporter): reported_store (重複送信抑制)"`

---

### Task 2.3 — `formatter.py` GitHub Issue Markdown body

**Files**
- Create: `E:\00_Git\10_NotebookOllama\core\crash_reporter\formatter.py`
- Test: `E:\00_Git\10_NotebookOllama\tests\unit\crash_reporter\test_formatter.py` (Create)

**Interfaces**
- Consumes: `PendingCrash` (Task 2.1)。
- Produces: `build_issue_body(crash: PendingCrash) -> str` — 以下セクションを持つ Markdown を返す:
  ```
  ## 概要
  <exception_type>: <exception_message (safe)>

  ## 環境
  - CPU: ...
  - RAM: ...
  - GPU: ...
  - OS: ...
  - Python: ...

  ## スタックトレース
  ```
  <trace>
  ```

  ## 直近ログ (検疫済み)
  ```jsonl
  <log_tail>
  ```

  ---
  - crash_id: <id>
  - fingerprint: <fingerprint>
  - source: <source>
  ```
- Produces: `build_issue_title(crash: PendingCrash) -> str` — `"[crash] <exception_type>: <safe_message (~60 chars)>"`。
- Produces: `default_labels(crash: PendingCrash) -> list[str]` — `["crash-auto", "needs-triage"]`。

**Steps**

1. **(red) テスト作成。** 固定入力に対する snapshot 的アサーション (`"## スタックトレース"` セクションがある、`crash_id` が body 末尾にある、title 長 ≤ 80 文字、labels = `["crash-auto", "needs-triage"]`)。

2. **(run-fail)** → `ModuleNotFoundError`。

3. **(green) 実装。**

4. **(run-pass)**。

5. **(commit)** `git commit -m "feat(crash-reporter): formatter (Issue body Markdown 生成)"`

---

### Task 2.4 — `prefill_url.py` 8KB 制限対応 URL Builder

**Files**
- Create: `E:\00_Git\10_NotebookOllama\core\crash_reporter\prefill_url.py`
- Test: `E:\00_Git\10_NotebookOllama\tests\unit\crash_reporter\test_prefill_url.py` (Create)

**Interfaces**
- Consumes: `MAX_URL_LEN`, `REPO_SLUG` (Task 1.0)。
- Produces: `build_issue_url(*, title: str, body: str, labels: list[str], repo: str = REPO_SLUG) -> tuple[str, bool]` — `(url, truncated_flag)`。spec §10 のアルゴリズム:
  1. 全部入りで URL 構築。`len(url) <= MAX_URL_LEN` なら `(url, False)`。
  2. body の末尾ログセクションを段階的に [50, 30, 20, 10] 行へ切詰めて再構築。収まったらそこで `(url, True)`。
  3. 最終手段: ログセクションを「ログが長すぎて URL に収まりませんでした…」マーカーで置換 → `(url, True)`。
- Produces: 内部ヘルパ `_trim_log_section(body, n_lines)` / `_replace_log_section(body, marker)` を `## 直近ログ (検疫済み)` 見出しの後の fenced block を対象に。

**Steps**

1. **(red) テスト作成。** 以下:
   - 短い body → `truncated=False`、URL に `github.com/KawanoMomo/notebook-ollama/issues/new?` が含まれる。
   - 7KB 超の body → `truncated=True`、URL 長 ≤ `MAX_URL_LEN`。
   - URL エンコード: 日本語タイトルが正しく percent-encoded されている。
   - `labels` がカンマ区切りクエリパラメータとして含まれる (`labels=crash-auto,needs-triage`)。
   - 極端に長い body (50,000 char) でも最終マーカー置換で必ず収まる。

2. **(run-fail)** → `ModuleNotFoundError`。

3. **(green) 実装。** `urllib.parse.urlencode(..., quote_via=quote_plus)`。

4. **(run-pass)**。

5. **(commit)** `git commit -m "feat(crash-reporter): prefill_url builder (8KB 制限段階切詰め)"`

---

### Sprint 2 ゲート

- `uv run pytest tests/unit/crash_reporter/ -q` → 全 pass。
- `uv run pytest -q` → 既存テスト全 pass。
- Draft PR に push。

---

## Sprint 3 — バックエンド traps + crash ルータ + feedback_hub ルータ + DomainError

**Scope:** spec §4.1 ①②③ のトラップ統合 + spec §6.3 `DomainError` 階層 + spec §7.1 API endpoints。`apps/api/main.py` lifespan に register() を結線。

**Deliverables:**
- `core/exceptions.py` に `DomainError` ベース追加 + 既存 `AppError` を `DomainError` 継承に整理 (後方互換維持)。
- `core/crash_reporter/collector.py` (traps 統合 + register)。
- `core/crash_reporter/settings.py` (CrashReportSettings + permissions 判定)。
- `core/feedback_hub/__init__.py`, `notice_store.py`, `feedback_formatter.py`。
- `apps/api/routers/crash.py` (5 endpoints)。
- `apps/api/routers/feedback_hub.py` (3 endpoints)。
- `apps/api/main.py` lifespan に `collector.register(app, ctx)` を結線。
- `apps/api/dependencies.py` の `AppContext` に `crash_collector` / `notice_store` を追加。
- `data/notices.json` の初版 (空配列または 1 件サンプル)。

### Task 3.1 — `DomainError` 階層と既存 `AppError` 互換

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\core\exceptions.py`
- Test: `E:\00_Git\10_NotebookOllama\tests\unit\test_exceptions.py` (Modify — 既存テスト + 新規アサーション追加)
- Test: `E:\00_Git\10_NotebookOllama\tests\unit\crash_reporter\test_domain_error.py` (Create)

**Interfaces**
- Produces: `class DomainError(Exception)` — `safe_message: ClassVar[str] = ""` を持つ。サブクラスは safe_message を override する。`redact_exception_message` (Task 1.1) と整合。
- Produces: `AppError` は **そのまま** で残し、別途 `DomainError` を導入 (後方互換)。`AppError` も `DomainError` を継承して将来 safe_message を持てるようにするが、Sprint 3 ではまず継承だけ追加し safe_message は空のまま。
- Produces (移行例): `class MissingQdrantCollection(DomainError): safe_message = "Qdrant collection not found"` を `core/crash_reporter/domain_errors.py` (Create) に置く (既存コードベース migration は spec §15 で「随時」と明記、本 plan ではサンプル 1 件のみ追加)。

**Steps**

1. **(red) テスト作成。** `tests/unit/crash_reporter/test_domain_error.py`:
   ```python
   from core.crash_reporter.redactor import redact_exception_message
   from core.crash_reporter.domain_errors import MissingQdrantCollection


   def test_domain_error_safe_message_is_emitted():
       err = MissingQdrantCollection("internal detail leaks here")
       assert redact_exception_message(err) == "Qdrant collection not found"


   def test_app_error_still_works():
       from core.exceptions import AppError, ErrorCode
       err = AppError(ErrorCode.STORAGE_NOT_FOUND, "x")
       # AppError は safe_message を持たないので型名フォールバック
       msg = redact_exception_message(err)
       assert "AppError" in msg
   ```

2. **(run-fail)** → `ModuleNotFoundError: core.crash_reporter.domain_errors`。

3. **(green) 実装。**
   a. `core/exceptions.py` に `DomainError` を追加 (`AppError` の dataclass はそのまま、`class DomainError(Exception): safe_message: str = ""`)。
   b. `core/crash_reporter/domain_errors.py` を新規作成し `MissingQdrantCollection` 1 件追加。

4. **(run-pass)** `uv run pytest tests/unit/crash_reporter/test_domain_error.py tests/unit/test_exceptions.py -q`。

5. **(commit)** `git commit -m "feat(exceptions): DomainError 階層 + crash_reporter.domain_errors.MissingQdrantCollection"`

---

### Task 3.2 — `core/crash_reporter/settings.py` + `core/config.py` 結線

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\core\config.py` (`CrashReportSettings` 追加 + `AppConfig.crash_report`)
- Modify: `E:\00_Git\10_NotebookOllama\core\settings_store.py` (`apply_overrides` で `crash_report` セクションも復元)
- Modify: `E:\00_Git\10_NotebookOllama\apps\api\schemas\settings.py` (`CrashReportSettingsSchema` 追加 + `AppSettingsSchema.crash_report`)
- Modify: `E:\00_Git\10_NotebookOllama\apps\api\routers\settings.py` (`get_settings` で `crash_report` を返す + `PUT /api/settings/crash-report`)
- Test: `E:\00_Git\10_NotebookOllama\tests\unit\test_audio_config_defaults.py` (Modify — `crash_report` 既定確認を追加)
- Test: `E:\00_Git\10_NotebookOllama\tests\integration\test_api\test_settings_crash_report.py` (Create)

**Interfaces**
- Produces: `class CrashReportSettings(BaseModel)` フィールド:
  - `enabled: bool | None = None` (`None` = 未決定、初回オプトイン未完了)
  - `auto_prompt: bool = True`
  - `opted_in_at: str | None = None` (ISO 8601 文字列)
- Produces: `AppConfig.crash_report: CrashReportSettings = Field(default_factory=...)`
- Produces: `AppSettingsSchema.crash_report: CrashReportSettingsSchema` (`GET /api/settings` に追加)
- Produces: `PUT /api/settings/crash-report` body=`CrashReportSettingsSchema` → 200 round-trip + `save_section("crash_report", ...)`

**Steps**

1. **(red) 統合テスト。** `tests/integration/test_api/test_settings_crash_report.py`:
   - `GET /api/settings` の `crash_report` ブロックが `{enabled: None, auto_prompt: True, opted_in_at: None}` を含むこと。
   - `PUT /api/settings/crash-report` で `enabled=True` + `opted_in_at="2026-06-28T00:00:00Z"` を送ると round-trip し、再 `GET` で同値が返ること。
   - 再 `TestClient` でも (= 再起動シミュ) 永続値が復元されること (`monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))` の共有)。

2. **(run-fail)** → `KeyError: 'crash_report'`。

3. **(green) 実装。**
   a. `core/config.py`: `CrashReportSettings` モデルと `AppConfig.crash_report` フィールド。
   b. `core/settings_store.py::apply_overrides`: `audio` / `ollama` と同じパターンで `crash_report` セクションを復元。
   c. `apps/api/schemas/settings.py`: `CrashReportSettingsSchema` と `AppSettingsSchema.crash_report`。
   d. `apps/api/routers/settings.py`: `get_settings` で `crash_report=CrashReportSettingsSchema(...)` を含める。`@router.put("/settings/crash-report")` 追加。

4. **(run-pass)** → 全 pass。

5. **(commit)** `git commit -m "feat(settings): CrashReportSettings を config/API/永続化に追加"`

---

### Task 3.3 — `pending_store` 等のディレクトリ作成 (`AppConfig.crash_pending_dir`)

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\core\config.py` (`crash_pending_dir` property + `ensure_dirs` に追加)
- Test: `E:\00_Git\10_NotebookOllama\tests\unit\test_config.py` (Modify — `crash_pending_dir` アサーション追加)

**Interfaces**
- Produces: `AppConfig.crash_pending_dir -> Path` (= `data_dir / "crash-pending"`)
- Produces: `ensure_dirs()` が `crash_pending_dir` も作成する。

**Steps**

1. **(red)** 既存 `test_config.py` に `assert config.crash_pending_dir == config.data_dir / "crash-pending"` と `config.ensure_dirs(); assert config.crash_pending_dir.is_dir()`。

2. **(run-fail)** → `AttributeError`。

3. **(green)** `core/config.py` に `@property` 追加 + `ensure_dirs` のタプルに `self.crash_pending_dir` を追加。

4. **(run-pass)**。

5. **(commit)** `git commit -m "feat(config): crash_pending_dir を追加し ensure_dirs で作成"`

---

### Task 3.4 — `core/crash_reporter/collector.py` traps 統合と register API

**Files**
- Create: `E:\00_Git\10_NotebookOllama\core\crash_reporter\collector.py`
- Test: `E:\00_Git\10_NotebookOllama\tests\integration\crash_reporter\__init__.py` (空)
- Test: `E:\00_Git\10_NotebookOllama\tests\integration\crash_reporter\test_collector.py` (Create)

**Interfaces**
- Consumes: `redactor`, `fingerprint`, `hardware`, `pending_store`, `reported_store`, `CrashReportSettings` (Task 3.2)。
- Produces: `class CrashCollector` (`__init__(self, *, data_dir: Path, settings_getter: Callable[[], CrashReportSettings], app_root: Path)`).
- Produces: `CrashCollector.handle_exception(exc: BaseException, *, source: str, log_tail: list[dict] | None = None) -> PendingCrash | None` — 全 traps が呼ぶ統合点。`enabled=False` なら no-op。`is_reported(fingerprint)` なら no-op。redactor / fingerprint / hardware を呼んで `PendingCrash` を `save`、そのレコードを返す (`None` は無効化 or 重複)。
- Produces: `CrashCollector.register(self, app: FastAPI) -> None` — FastAPI exception handler / `sys.excepthook` / signal (SIGTERM/SIGINT, Unix のみ。Windows は SIGTERM 相当の `SIGBREAK` も追加) / `atexit.register` をすべてセットする。`unregister` も同期で呼べるようにし、`lifespan` 終了時に呼ぶ。

**Steps**

1. **(red) 統合テスト。** `tests/integration/crash_reporter/test_collector.py`:
   - **handle_exception_enabled_path**: `CrashCollector` に `RuntimeError` を投げると `crash-pending/<id>.json` が 1 件できる、`PendingCrash` が返る。
   - **handle_exception_disabled_returns_none**: `settings.enabled=False` なら何もせず `None` を返す、ファイルもできない。
   - **handle_exception_dedupe_via_reported_store**: 同じ traceback で 2 度呼ぶと 2 件目は `None`、ファイルは 1 件のまま。
   - **handle_exception_caps_log_tail_size**: 5,000 行渡しても `log_tail` は安全に保存される (redactor 経由)。
   - **register_attaches_fastapi_exception_handler**: `app = FastAPI(); collector.register(app); @app.get("/boom") def b(): raise RuntimeError("x")` → `TestClient(app).get("/boom")` 後に `pending_store.load_all` が 1 件返す。register したハンドラは元の AppError ハンドラを壊さない (`AppError(STORAGE_NOT_FOUND)` は依然として 404 を返す → 既存 `tests/integration/test_api/test_sources_api.py` 系を回帰で確認)。

2. **(run-fail)** → `ModuleNotFoundError`。

3. **(green) 実装方針。**
   - `CrashCollector.register` は app instance に `add_exception_handler(Exception, ...)` を追加。**注意**: 既存の `AppError` ハンドラ (`apps/api/main.py` L106) より**狭い型を優先** したいので、AppError ハンドラを **先に登録** → その後 `Exception` 用 fallback を register する流れに統一する (FastAPI は型の階層に基づき適切なハンドラを呼ぶ)。
   - `sys.excepthook` は退避 `_original_excepthook = sys.excepthook` してチェイン (呼んだ後オリジナルを呼ぶ)。
   - signal は `signal.signal(SIGTERM, ...)` / `signal.signal(SIGINT, ...)` をセット (Windows は `SIGBREAK` も)。ハンドラ内で `handle_exception(KeyboardInterrupt("signal=<n>"), source="signal")` 相当を呼んで `raise SystemExit(128 + n)` で終了。
   - `atexit.register` は「register の前に handle_exception された crash 以外で、最後の `sys.exc_info()` を見て例外がある場合のみ収集」(spec §4.1 ②④ にある atexit は unhandled が逃げた最後の保険)。
   - `unregister` は `sys.excepthook = _original_excepthook`、signal を `SIG_DFL` に戻す、`atexit` は標準では unregister 不可なのでフラグで disable。
   - `register` した collector の参照は `app.state.crash_collector` に保存し、Sprint 4 の lifecycle がアクセスできるようにする。

4. **(run-pass)** → 全 pass。

5. **(commit)** `git commit -m "feat(crash-reporter): collector (traps 統合 + register/unregister)"`

---

### Task 3.5 — `apps/api/routers/crash.py` 5 endpoints

**Files**
- Create: `E:\00_Git\10_NotebookOllama\apps\api\routers\crash.py`
- Create: `E:\00_Git\10_NotebookOllama\apps\api\schemas\crash.py`
- Modify: `E:\00_Git\10_NotebookOllama\apps\api\main.py` (router include + `collector.register(app)` を lifespan に追加 + `unregister` を yield 後で呼ぶ)
- Modify: `E:\00_Git\10_NotebookOllama\apps\api\dependencies.py` (`AppContext.crash_collector: CrashCollector` 追加 + `build_context` で `CrashCollector(...)` をインスタンス化)
- Test: `E:\00_Git\10_NotebookOllama\tests\integration\test_api\test_crash_endpoints.py` (Create)

**Interfaces**
- Produces (HTTP, spec §7.1):
  - `GET /api/crash/pending` → `list[CrashPendingItem]` (作成日時降順)
  - `POST /api/crash/report` body=`FrontendCrashReport {message: str, stack: str, url: str, user_agent: str}` → 201 + `CrashPendingItem` (フロント例外通知の永続化用)
  - `POST /api/crash/{id}/dismiss` → 204 (`pending_store.delete`)
  - `GET /api/crash/{id}/prefill-url` → `{url: str, truncated: bool}`
  - `POST /api/crash/{id}/mark-reported` → 204 (`reported_store.mark_reported` + `pending_store.delete`)
- Produces (schemas, `apps/api/schemas/crash.py`):
  - `class CrashPendingItem(BaseModel)` (`PendingCrash` を 1:1 で写像)
  - `class FrontendCrashReport(BaseModel)`
  - `class PrefillUrlResponse(BaseModel)` (`{url: str, truncated: bool}`)

**Steps**

1. **(red) テスト作成。** `tests/integration/test_api/test_crash_endpoints.py`:
   - `pending_store.save` で 2 件投入 → `GET /api/crash/pending` で 200 + 2 件、`created_at` 降順。
   - `POST /api/crash/report {"message": "...", ...}` → 201 + 永続化、再度 `GET pending` で件数 +1。
   - `POST /api/crash/<unknown>/dismiss` → 204 (no-op でも 204、設計判断)。
   - `POST /api/crash/<existing>/dismiss` → 204 + 後続 `GET pending` で件数 -1。
   - `GET /api/crash/<existing>/prefill-url` → 200 + `url.startswith("https://github.com/KawanoMomo/notebook-ollama/issues/new?")` + `truncated` boolean。
   - `POST /api/crash/<existing>/mark-reported` → 204 + `reported.txt` に fingerprint 1 件追記 + `pending` から削除。
   - **Auth ガード**: `settings.enabled=False` のとき `POST /api/crash/report` は 403 を返す ([[feedback-no-data-guarantee-in-ui]] 上はオプトイン未完了でも黙って受け取り捨てない方が明示的、403 + body `error.code="crash_report.disabled"`)。`enabled=None` (オプトイン未決) も 403。`enabled=True` のみ受理。

2. **(run-fail)** → 404 全部 (route 未定義)。

3. **(green) 実装。**
   a. `apps/api/schemas/crash.py`: 上記 3 schemas。
   b. `apps/api/routers/crash.py`: `router = APIRouter(prefix="/api/crash", tags=["crash"])`、5 endpoints。`request.app.state.ctx` から `crash_collector`, `config.data_dir`, `config.crash_report.enabled` を取り出す。
   c. `apps/api/dependencies.py`: `AppContext.crash_collector` フィールド + `build_context` で `CrashCollector(data_dir=config.data_dir, settings_getter=lambda: config.crash_report, app_root=Path(__file__).parents[2])` を生成し AppContext に詰める。
   d. `apps/api/main.py`: lifespan で `app.state.ctx.crash_collector.register(app)` 呼出 + `yield` 後 `unregister()`。
   e. `core/exceptions.py` に `CRASH_REPORT_DISABLED = "crash_report.disabled"` を追加し、`apps/api/main.py` の `status_map` に `"crash_report.disabled": 403` を追加。

4. **(run-pass)** → 全 pass。

5. **(commit)** `git commit -m "feat(api): /api/crash/* 5 endpoints + collector を lifespan に結線"`

---

### Task 3.6 — `core/feedback_hub/notice_store.py` + `data/notices.json`

**Files**
- Create: `E:\00_Git\10_NotebookOllama\core\feedback_hub\__init__.py` (空)
- Create: `E:\00_Git\10_NotebookOllama\core\feedback_hub\notice_store.py`
- Create: `E:\00_Git\10_NotebookOllama\data\notices.json`
- Test: `E:\00_Git\10_NotebookOllama\tests\unit\test_notice_store.py` (Create)

**Interfaces**
- Produces: `@dataclass class Notice` (id: str, published_at: str (YYYY-MM-DD), title: str, body_markdown: str, subsections: dict[str, list[str]] | None)
- Produces: `load_notices(path: Path) -> list[Notice]` — JSON ファイルから `Notice` リストを返す。`published_at` 降順でソート。ファイルが無ければ `[]`。壊れていれば `[]` (起動を止めない、log.warning)。
- `data/notices.json` の初版スキーマ (Sprint 6 で再利用):
  ```json
  {
    "notices": [
      {
        "id": "2026-06-28-launch",
        "published_at": "2026-06-28",
        "title": "クラッシュレポート & フィードバックハブを公開しました",
        "body_markdown": "...",
        "subsections": {
          "新機能": ["ヘッダの拡声器からお知らせ・不具合・ご意見を送れます"],
          "改善": []
        }
      }
    ]
  }
  ```

**Steps**

1. **(red) テスト作成。**
   - 有効 JSON → `len(load_notices(path)) >= 1`、`Notice.id == "2026-06-28-launch"`。
   - ファイル不在 → `[]`。
   - 壊れた JSON → `[]` (例外を throw しない)。
   - 複数件で `published_at` 降順。

2. **(run-fail)** → `ModuleNotFoundError`。

3. **(green) 実装。** `data/notices.json` を 1 件含む初版で作成 (リポジトリにコミット、`.gitignore` で除外しない)。

4. **(run-pass)**。

5. **(commit)** `git commit -m "feat(feedback-hub): notice_store + data/notices.json 初版"`

---

### Task 3.7 — `core/feedback_hub/feedback_formatter.py` + `apps/api/routers/feedback_hub.py`

**Files**
- Create: `E:\00_Git\10_NotebookOllama\core\feedback_hub\feedback_formatter.py`
- Create: `E:\00_Git\10_NotebookOllama\apps\api\routers\feedback_hub.py`
- Create: `E:\00_Git\10_NotebookOllama\apps\api\schemas\feedback_hub.py`
- Modify: `E:\00_Git\10_NotebookOllama\apps\api\main.py` (router include)
- Modify: `E:\00_Git\10_NotebookOllama\apps\api\dependencies.py` (`AppContext.notice_store_path: Path` 追加; デフォルト `Path(__file__).parents[2] / "data" / "notices.json"`)
- Test: `E:\00_Git\10_NotebookOllama\tests\integration\test_api\test_feedback_hub_endpoints.py` (Create)

**Interfaces**
- Produces (Python):
  - `class FeedbackInput(BaseModel)` (`category: Literal["feature", "ux", "impression"]`, `body: str`, `sentiment: Literal["up", "neutral", "down"] | None`)
  - `build_feedback_body(fb: FeedbackInput) -> str` — Markdown body 生成 (種別見出し + 本文 + 感情)。スクショは body 末尾に「スクリーンショットは手動でこの Issue にドラッグ&ドロップしてください」案内文を入れる。
  - `build_feedback_title(fb: FeedbackInput) -> str` — `"[feedback] (機能要望) <body の先頭 40 char>"` 等。
- Produces (HTTP):
  - `GET /api/feedback-hub/notices` → `{notices: list[Notice]}`
  - `GET /api/feedback-hub/unread-count` → `{notices_total: int, pending_crashes: int, total: int}` (お知らせは backend では「未読」を判定できないため `notices_total` を返してフロントが localStorage で差し引く設計)
  - `POST /api/feedback-hub/feedback` body=`FeedbackInput` → `{url: str, truncated: bool}` (`build_issue_url` を category=`feature/ux/impression` に応じた labels `["feedback", "category:<cat>"]` で生成)

**Steps**

1. **(red) テスト作成。** `tests/integration/test_api/test_feedback_hub_endpoints.py`:
   - `GET /api/feedback-hub/notices` → 200 + `notices` 配列 (data/notices.json から)。
   - `GET /api/feedback-hub/unread-count` → 200 + `{notices_total: <int>, pending_crashes: <int>, total: <sum>}`。
   - `POST /api/feedback-hub/feedback {category: "feature", body: "X", sentiment: "up"}` → 200 + `url.startswith("https://github.com/")`, `labels=feedback,category:feature` をクエリで確認。
   - `body` が空 → 422 (pydantic min_length バリデーション)。

2. **(run-fail)** → 404。

3. **(green) 実装。** schema / formatter / router を順に。

4. **(run-pass)**。

5. **(commit)** `git commit -m "feat(feedback-hub): /api/feedback-hub/* 3 endpoints + feedback_formatter"`

---

### Sprint 3 ゲート

- `uv run pytest -q` → 全 pass (新規 + 既存全て)。
- 念のため `uv run pytest tests/integration/test_api/test_sources_api.py tests/integration/test_api/test_recordings_api.py -q` で AppError ハンドラ回帰なしを確認。
- Draft PR に push。

---

## Sprint 4 — `lifecycle.py` (unclean shutdown 検知)

**Scope:** spec §4.1 ④ + §7.2 `running.lock` + psutil PID 確認 + `last-session.log` tail 採取。Sprint 3 の collector とは独立に登録されるが、登録順は collector の後 (collector が pending_store を解決できる必要があるため)。

**Deliverables:**
- `core/crash_reporter/lifecycle.py`
- `apps/api/main.py` lifespan で `lifecycle.check_unclean_shutdown(...)` 呼出 → 必要なら collector に流す。
- `apps/api/main.py` lifespan で `lifecycle.write_lock(...)` + finally で `lifecycle.clear_lock(...)`。
- 構造化ログを `data_dir / "logs" / "last-session.log"` に書く処理 (`core/logging.py` 拡張)。

### Task 4.1 — `core/logging.py` を `last-session.log` 出力に拡張

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\core\logging.py`
- Test: `E:\00_Git\10_NotebookOllama\tests\unit\test_logging.py` (Modify)

**Interfaces**
- Produces: `configure_logging(level: str = "INFO", *, logs_dir: Path | None = None, stream: TextIO | None = None)` — `logs_dir` が指定されたら `logs_dir / "last-session.log"` を **起動時に truncate** し、構造化 JSON を **追記** で書き出す。stderr 出力は維持。
- 既存呼び出し (`apps/api/main.py::lifespan`) を `configure_logging(logs_dir=config.logs_dir)` に変更する。

**Steps**

1. **(red) テスト変更。** `test_logging.py` に「`logs_dir` 指定で `last-session.log` がトラケート + structlog 出力が追記される」テストを追加。

2. **(run-fail)** → `last-session.log` ファイル不在。

3. **(green) 実装。** `logging.FileHandler(logs_dir / "last-session.log", mode="w")` を追加し、root logger に attach。structlog の `JSONRenderer` 出力がそのまま流れる。

4. **(run-pass)** + 既存 `test_logging.py` の他テストも pass。

5. **(commit)** `git commit -m "feat(logging): last-session.log 出力 (起動時 truncate)"`

---

### Task 4.2 — `core/crash_reporter/lifecycle.py` running.lock + psutil

**Files**
- Create: `E:\00_Git\10_NotebookOllama\core\crash_reporter\lifecycle.py`
- Test: `E:\00_Git\10_NotebookOllama\tests\integration\crash_reporter\test_lifecycle.py` (Create)

**Interfaces**
- Produces: `write_lock(data_dir: Path) -> None` — `data_dir/running.lock` に現在 PID を書く (atomic)。
- Produces: `clear_lock(data_dir: Path) -> None` — `unlink(missing_ok=True)`。
- Produces: `check_unclean_shutdown(*, data_dir: Path, logs_dir: Path) -> dict | None` — lock がある && PID が生きていない → `last-session.log` を tail 100 行採取して `{tail: list[str], previous_pid: int}` を返す。生きていれば `None` (uvicorn --reload の正常再起動の可能性、何もしない)。
- Consumes (optional): `psutil` (Sprint 1 と同じ try/except)。`psutil` が無ければ「生死判定不可」と扱い、安全側で `None` を返す (誤検知より見逃しを許す)。

**Steps**

1. **(red) 統合テスト。** `test_lifecycle.py`:
   - `write_lock(tmp_path)` で `running.lock` が現在 PID で作られる。
   - `clear_lock` で消える。`missing_ok` で 2 度呼んでも例外なし。
   - `check_unclean_shutdown`: PID が「絶対に存在しない値」(例 `os.getpid() + 999999`) を lock に書いた場合 + `last-session.log` を 200 行で作っておくと、tail 100 行が返る。
   - 現在 PID で lock を書いた場合は `None`。
   - lock 不在で `None`。
   - psutil が無い (`monkeypatch.setattr(lifecycle, "_psutil", None)`) → 安全側 `None`。

2. **(run-fail)** → `ModuleNotFoundError`。

3. **(green) 実装。** atomic write は Sprint 2 と同じ tmp + replace パターン。

4. **(run-pass)** → 全 pass。

5. **(commit)** `git commit -m "feat(crash-reporter): lifecycle (running.lock + psutil 死活)"`

---

### Task 4.3 — `apps/api/main.py` lifespan で lifecycle を結線

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\apps\api\main.py`
- Test: `E:\00_Git\10_NotebookOllama\tests\integration\test_api\test_unclean_shutdown_detection.py` (Create)

**Interfaces**
- Produces: `lifespan` で:
  1. `configure_logging(logs_dir=config.logs_dir)` (Task 4.1)
  2. `previous = lifecycle.check_unclean_shutdown(data_dir=config.data_dir, logs_dir=config.logs_dir)`
  3. `if previous:` → `crash_collector.handle_unclean_shutdown(log_tail=previous["tail"], previous_pid=previous["previous_pid"])` で `PendingCrash(source="unclean_shutdown")` を保存。
  4. `lifecycle.write_lock(config.data_dir)`
  5. `yield`
  6. (finally) `lifecycle.clear_lock(config.data_dir)`

- Produces: `CrashCollector.handle_unclean_shutdown(*, log_tail: list[str], previous_pid: int) -> PendingCrash | None` — Sprint 3 で `handle_exception` だけ持っていた collector に追加。redactor で log_tail を検疫し、fingerprint は固定文字列 (`"unclean_shutdown::<top_line_hash>"`) を使う (例外オブジェクトが無いため)。

**Steps**

1. **(red) 統合テスト。** `test_unclean_shutdown_detection.py`:
   - `tmp_path / "running.lock"` に絶対に存在しない PID + `tmp_path / "logs" / "last-session.log"` に擬似ログを置く → `TestClient(app).get("/api/health")` の起動 (lifespan) 後、`tmp_path / "crash-pending"` に 1 件 JSON。

2. **(run-fail)** → ファイル不在 / `AttributeError: handle_unclean_shutdown`。

3. **(green) 実装。**
   a. `CrashCollector.handle_unclean_shutdown` を Sprint 3 の collector に追加。
   b. `apps/api/main.py::lifespan` を上記順序で改修。

4. **(run-pass)** → 全 pass。

5. **(regression)** `uv run pytest -q` 全 pass を確認 (lifespan 改修で他テストが壊れないこと)。

6. **(commit)** `git commit -m "feat(crash-reporter): lifespan に unclean shutdown 検知 + lock 管理を結線"`

---

### Sprint 4 ゲート

- `uv run pytest -q` → 全 pass。
- `uv run uvicorn apps.api.main:app --reload --port 8765` で手動起動して `~/.notebook-ollama/running.lock` が作られ、Ctrl+C 後に消えることを確認 (smoke test、PR 説明に記録)。
- Draft PR に push。

---

## Sprint 5 — フロント: 旗ハブ Drawer 枠 + 即時モーダル + プレビュー

**Scope:** ヘッダの Megaphone アイコン、右側 Drawer (440px、3 タブ枠だけ)、クラッシュ即時モーダル、プレビュー編集ダイアログ、フロント `window.onerror` 連携、API client / store の基盤。

**Deliverables:**
- `apps/web/src/lib/api/crash.ts`, `feedbackHub.ts`
- `apps/web/src/lib/stores/feedbackHub.svelte.ts`, `crashReports.svelte.ts`
- `apps/web/src/lib/components/FeedbackHubDrawer.svelte` (枠 + タブ切替のみ。中身はプレースホルダ)
- `apps/web/src/lib/components/CrashDetectionModal.svelte`
- `apps/web/src/lib/components/CrashPreviewDialog.svelte`
- `apps/web/src/lib/utils/errorBoundary.ts`
- `apps/web/src/lib/components/AppHeader.svelte` 改修 (Megaphone + 未読ドット)
- `apps/web/src/routes/+layout.svelte` 改修 (errorBoundary 起動 + Drawer / Modal の mount)
- `apps/web/src/lib/api/types.ts` に crash/feedback 関連型を追加

**Tech stack 補足:** `@lucide/svelte` の `Megaphone` は既にインストール済 (`AppHeader` で `Settings` が import されている前例)。 `html2canvas` は Sprint 8 まで不要。

### Task 5.1 — `apps/web/src/lib/api/types.ts` 拡張

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\api\types.ts`

**Interfaces**
- Produces:
  ```ts
  export interface CrashPendingItem {
    id: string;
    fingerprint: string;
    created_at: string;
    exception_type: string;
    exception_message: string;
    trace: string[];
    hardware: Record<string, string | number | null>;
    log_tail: Array<Record<string, unknown>>;
    source: "fastapi" | "excepthook" | "signal" | "atexit" | "frontend" | "unclean_shutdown";
  }
  export interface FrontendCrashReport {
    message: string;
    stack: string;
    url: string;
    user_agent: string;
  }
  export interface PrefillUrlResponse {
    url: string;
    truncated: boolean;
  }
  export interface Notice {
    id: string;
    published_at: string;
    title: string;
    body_markdown: string;
    subsections: Record<string, string[]> | null;
  }
  export interface UnreadCounts {
    notices_total: number;
    pending_crashes: number;
    total: number;
  }
  export interface FeedbackInput {
    category: "feature" | "ux" | "impression";
    body: string;
    sentiment: "up" | "neutral" | "down" | null;
  }
  export interface CrashReportSettings {
    enabled: boolean | null;
    auto_prompt: boolean;
    opted_in_at: string | null;
  }
  ```
- Modify: `AppSettings` に `crash_report: CrashReportSettings` を追加。

**Steps**

1. (no test、純粋型追加) `npm run check` のみがゲート。

2. **(green) 編集。**

3. **(gate)** `cd apps/web && npm run check` → 0 errors。

4. **(commit)** `git commit -m "feat(web): crash/feedback 型を types.ts に追加"`

---

### Task 5.2 — `apps/web/src/lib/api/crash.ts` + `feedbackHub.ts`

**Files**
- Create: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\api\crash.ts`
- Create: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\api\feedbackHub.ts`

**Interfaces**
- Produces (`crash.ts`):
  - `crashApi.pending(): Promise<CrashPendingItem[]>`
  - `crashApi.report(body: FrontendCrashReport): Promise<CrashPendingItem>`
  - `crashApi.dismiss(id: string): Promise<void>`
  - `crashApi.prefillUrl(id: string): Promise<PrefillUrlResponse>`
  - `crashApi.markReported(id: string): Promise<void>`
- Produces (`feedbackHub.ts`):
  - `feedbackHubApi.notices(): Promise<{ notices: Notice[] }>`
  - `feedbackHubApi.unreadCount(): Promise<UnreadCounts>`
  - `feedbackHubApi.feedback(body: FeedbackInput): Promise<PrefillUrlResponse>`
- Consumes: `request<T>` from `./client.ts` (既存パターン: `sources.ts` 参照)。

**Steps**

1. **(green) 実装。** `sources.ts` / `settings.ts` の書き方に従って既存 `request` でラップ。

2. **(gate)** `cd apps/web && npm run check && npm run build` → 0 errors / build 成功。

3. **(commit)** `git commit -m "feat(web): crashApi / feedbackHubApi クライアントを追加"`

---

### Task 5.3 — `feedbackHub.svelte.ts` / `crashReports.svelte.ts` stores

**Files**
- Create: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\stores\feedbackHub.svelte.ts`
- Create: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\stores\crashReports.svelte.ts`
- Create: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\stores\notices.svelte.ts` (Sprint 6 で中身を充填するが、Sprint 5 で `unreadCount` 用に基盤を作る)

**Interfaces**
- Produces (`feedbackHub.svelte.ts`):
  ```ts
  class FeedbackHubStore {
    drawerOpen = $state(false);
    activeTab = $state<'notices' | 'bugs' | 'feedback'>('notices');
    unreadCount = $derived(noticesStore.unreadCount + crashReportsStore.pendingCount);
    open(tab?: 'notices' | 'bugs' | 'feedback') {
      this.drawerOpen = true;
      if (tab) this.activeTab = tab;
    }
    close() { this.drawerOpen = false; }
  }
  export const feedbackHubStore = new FeedbackHubStore();
  ```
- Produces (`crashReports.svelte.ts`):
  ```ts
  class CrashReportsStore {
    pending = $state<CrashPendingItem[]>([]);
    pendingCount = $derived(this.pending.length);
    async load() {
      this.pending = await crashApi.pending();
    }
    async dismiss(id: string) { ... }
    async markReported(id: string) { ... }
  }
  ```
- Produces (`notices.svelte.ts`) Sprint 5 では最小:
  ```ts
  class NoticesStore {
    items = $state<Notice[]>([]);
    seenIds = $state<Set<string>>(new Set());  // Sprint 6 で localStorage バインド
    unreadCount = $derived(this.items.filter(n => !this.seenIds.has(n.id)).length);
    async load() { this.items = (await feedbackHubApi.notices()).notices; }
  }
  ```

**Steps**

1. **(green) 実装。**

2. **(gate)** `cd apps/web && npm run check` → 0 errors。

3. **(commit)** `git commit -m "feat(web): feedbackHub / crashReports / notices stores"`

---

### Task 5.4 — `AppHeader.svelte` に Megaphone + 未読ドット + Drawer 起動

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\AppHeader.svelte`

**Interfaces**
- Consumes: `feedbackHubStore` (Task 5.3)。
- Produces: `<button class="icon-btn" aria-label="お知らせ・フィードバック" onclick={() => feedbackHubStore.open()}>` 内に `<Megaphone size={18} stroke-width={1.75} />` + `feedbackHubStore.unreadCount > 0` のとき右上に `<span class="badge-dot" aria-label="未読あり" />` (6×6px、`#ef4444`、白リング)。
- 位置: 既存 `<a href="/settings">` の **直前** (左隣)。

**Steps**

1. **(green) 編集。** 既存の `<Settings />` import を `import { Megaphone, Settings } from '@lucide/svelte';` に拡張。

2. **(gate)** `cd apps/web && npm run check && npm run build` → 0 errors + build OK。

3. **(commit)** `git commit -m "feat(web): AppHeader に Megaphone アイコン + 未読ドットを追加"`

---

### Task 5.5 — `FeedbackHubDrawer.svelte` (枠 + タブ切替のみ)

**Files**
- Create: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\FeedbackHubDrawer.svelte`
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\routes\+layout.svelte` (`{#if feedbackHubStore.drawerOpen}<FeedbackHubDrawer />{/if}` を追加)

**Interfaces**
- Consumes: `feedbackHubStore` (Task 5.3)。
- Produces: spec §5.2 の幅 440px / 右側固定 / backdrop / ESC で close / 3 タブ (お知らせ / 不具合 / ご意見) underline tab。タブ内側は Sprint 6/7/8 でそれぞれ充填。Sprint 5 では `<p>(タブ内容は Sprint 6/7/8 で実装)</p>` のプレースホルダで描画する (視覚ゲート対象の最低限の構造)。
- アクセシビリティ: drawer 開いている間は `<svelte:window onkeydown={onKey} />` で ESC キャプチャ + focus を drawer 内に閉じ込めるのは MVP では省略 (Sprint 9 で issue 化)。
- 各タブの pill (未読/未送信数) は Sprint 6/7 でデータが入った後に表示判定 (Sprint 5 では Sprint 5 で取得済の `crashReportsStore.pendingCount` だけ 不具合タブに付与)。

**Steps**

1. **(green) 実装。** Modal.svelte の backdrop パターンを流用 (右側 slide-in は CSS `transform: translateX(0)` + `transition`)。

2. **(gate)** `cd apps/web && npm run check && npm run build` → 0 errors + build OK。

3. **(commit)** `git commit -m "feat(web): FeedbackHubDrawer 枠 + 3 タブ切替"`

---

### Task 5.6 — `CrashDetectionModal.svelte` (即時モーダル)

**Files**
- Create: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\CrashDetectionModal.svelte`
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\routes\+layout.svelte` (mount)
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\stores\crashReports.svelte.ts` (`activeImmediate: CrashPendingItem | null = $state(null)` を追加)

**Interfaces**
- Consumes: `crashReportsStore.activeImmediate`。
- Produces: spec §5.6 のレイアウト。ヘッダ「⚠ エラーが発生しました」、本文に `exception_type: exception_message`、案内文「**次の画面で送信内容のプレビューが表示されます。** 内容を確認・編集してから送信できます。」、ボタン「今は送らない」/「送信内容をプレビュー →」。
- 「プレビュー →」押下で `crashPreviewStore.openFor(activeImmediate)` (Task 5.7 の store) を呼び、`activeImmediate = null`。
- **絶対禁止**: 「以下のデータが送信されます / 送信されません」リスト ([[feedback-no-data-guarantee-in-ui]])。

**Steps**

1. **(green) 実装。** `Modal.svelte` を継承するのではなく独立コンポーネントで OK (背景クリックで閉じない: 「今は送らない」明示クリック必須)。

2. **(gate)** `cd apps/web && npm run check && npm run build` → 0 errors / build。

3. **(commit)** `git commit -m "feat(web): CrashDetectionModal (即時モーダル、データ宣言なし)"`

---

### Task 5.7 — `CrashPreviewDialog.svelte` (プレビュー編集)

**Files**
- Create: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\CrashPreviewDialog.svelte`
- Create: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\stores\crashPreview.svelte.ts`
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\routes\+layout.svelte` (mount)

**Interfaces**
- Produces (`crashPreview.svelte.ts`):
  ```ts
  class CrashPreviewStore {
    crash = $state<CrashPendingItem | null>(null);
    title = $state('');
    body = $state('');
    labels = $state<string[]>([]);
    truncated = $state(false);
    async openFor(c: CrashPendingItem) {
      const res = await crashApi.prefillUrl(c.id);
      // url から title/body を逆引きせず、別に formatter API を作るか、prefillUrl
      // レスポンスに raw {title, body, labels} も含める方が筋がいい。
      // → spec §7.1 の prefill-url を {url, title, body, labels, truncated} に拡張
      //   (実装は Task 5.7 内で apps/api/routers/crash.py を Modify する小タスクを追加。
      //    Sprint 3 の Task 3.5 で先に書ければそれが望ましいが、ここで補完してよい)。
      this.crash = c;
      this.title = res.title;
      this.body = res.body;
      this.labels = res.labels;
      this.truncated = res.truncated;
    }
    close() { this.crash = null; }
  }
  ```
- **API 拡張 (Task 5.7 で行う backend 小修正):**
  - `apps/api/schemas/crash.py` の `PrefillUrlResponse` に `title: str`, `body: str`, `labels: list[str]` を追加。
  - `apps/api/routers/crash.py` の `GET /api/crash/{id}/prefill-url` の戻りを `{url, truncated, title, body, labels}` に更新。
  - 既存テスト `test_crash_endpoints.py` の prefill-url アサーションを更新 (`title.startswith("[crash]")` 等)。
- Produces (`CrashPreviewDialog.svelte`): spec §5.7 のレイアウト (min-width 720px、title input / labels chips / body textarea / フッタ「却下」「クリップボードにコピー」「GitHubで開く →」)。
  - 「却下」→ `crashApi.dismiss(crash.id)` + `crashReportsStore.load()` + `close()`。
  - 「コピー」→ `navigator.clipboard.writeText(body)` + `pushToast('クリップボードにコピーしました', 'success')`。
  - 「GitHubで開く →」→ `crashApi.prefillUrl` で **編集後の title/body を反映した URL を再生成** する必要があるため、フロント側でも `build_issue_url` 相当が要る。**設計判断**: 編集後 body をサーバに送り直して URL を再生成する `POST /api/crash/{id}/prefill-url` (body=`{title?: string, body?: string, labels?: string[]}`) を追加し、サーバ側 8KB 制限ロジックの一元化を保つ。
  - **API 追加 (Task 5.7 で行う backend 小修正 part 2):**
    - `apps/api/routers/crash.py` に `POST /api/crash/{id}/prefill-url` body=`{title?: str | None, body?: str | None, labels?: list[str] | None}` → `{url, truncated, title, body, labels}` 追加。未指定フィールドは pending_store の既定値を使う。
    - 既存 `GET` は読み取り専用 (デフォルト URL)、`POST` は編集後再生成と役割分離。
    - テストを `test_crash_endpoints.py` に 1 件追加。
  - 「GitHubで開く →」押下後の挙動: `window.open(url, '_blank')` + `crashApi.markReported(id)` + `crashReportsStore.load()` + `close()`。

**Steps**

1. **(red) backend 拡張テスト。** `test_crash_endpoints.py` に上記 GET 拡張 + POST 追加のテストを書く。

2. **(run-fail)** → 404 / KeyError。

3. **(green) backend 拡張実装。** schema + endpoints。

4. **(green) frontend 実装。** store + dialog コンポーネント。

5. **(gate)** `cd apps/web && npm run check && npm run build` → 0 errors + build。

6. **(run-pass)** `uv run pytest tests/integration/test_api/test_crash_endpoints.py -q`。

7. **(commit)** `git commit -m "feat(crash): prefill-url を編集後再生成可能に拡張 + フロントプレビューダイアログ"`

---

### Task 5.8 — `errorBoundary.ts` (フロント `window.onerror` / `unhandledrejection` → backend 通知)

**Files**
- Create: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\utils\errorBoundary.ts`
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\routes\+layout.svelte` (`onMount` で `initErrorBoundary()` 呼出)

**Interfaces**
- Produces: `initErrorBoundary(): () => void` (unbind 関数を返す)。
- 動作: `window.addEventListener('error', ...)` と `window.addEventListener('unhandledrejection', ...)` で `crashApi.report({...})` を呼ぶ。さらに `crashReportsStore.activeImmediate = <その crash>` をセットし即時モーダルを起動。**throttle**: 同一 message を 5 秒で 1 回まで (frontend で `Set<message>` + `setTimeout`)。
- `crashApi.report` が 403 (オプトイン未完了) を返した場合: 即時モーダルは出さず、コンソールに `console.warn` だけ。

**Steps**

1. **(green) 実装。**

2. **(gate)** `npm run check && npm run build` → 0 errors / build OK。

3. **(commit)** `git commit -m "feat(web): window.onerror / unhandledrejection を backend へ通知"`

---

### Sprint 5 視覚ゲート (controller / Evaluator が実行)

**前提**: `uv run uvicorn apps.api.main:app --reload --port 8765` + `cd apps/web && npm run dev`。

**Evaluator 検証項目** (全てスクショ必須、自動テスト GREEN だけで PASS 禁止 / [[feedback_visual_verification]]):
1. ヘッダ右端の歯車アイコンの**左隣**に Megaphone アイコンが表示される。サイズが歯車 (18px) と並べて違和感ないか目視。違和感あれば 16px / 20px を試し、final 値を **Sprint 9 Task 9.2** で記録。
2. Megaphone クリック → 右側 440px Drawer が slide-in。3 タブ underline 切替。
3. ESC / 背景クリックで Drawer が閉じる。
4. DevTools console に `throw new Error("test from devtools")` を打つ → `CrashDetectionModal` がポップ。「送信内容をプレビュー →」で `CrashPreviewDialog` が開き、title `[crash] Error...`、body に環境 / スタック / ログセクションが見える。「却下」で消える。
5. プレビュー画面で title を編集 → 「GitHubで開く →」押下で新規タブが開き、URL の `title=` パラメータが編集後の値で percent-encoded されている。`github.com/KawanoMomo/notebook-ollama/issues/new` で始まる。
6. console.error が 0 件 (バインドミスや HMR エラーが無いこと、F12 で確認)。
7. **未読ドット**: `crashApi.report({...})` を 1 回呼ぶと Megaphone 右上に 6×6 ドット (`#ef4444` + 白リング) が出る。

NG 時は self-fix 最大 3 回 (例: drawer の z-index 不足で modal が裏に隠れる→ z-index 200, drawer 150 に階層化)。スクショは PR 説明に添付。

PASS 後、Draft PR に push。

---

## Sprint 6 — お知らせタブ (timeline + localStorage 既読)

**Scope:** `NoticesTab.svelte` (Linear 風 timeline)、`localStorage` 既読管理、Megaphone 未読ドットへの寄与。

**Deliverables:**
- `apps/web/src/lib/components/feedback-hub/NoticesTab.svelte`
- `apps/web/src/lib/stores/notices.svelte.ts` の localStorage 永続化拡張
- `FeedbackHubDrawer.svelte` の「お知らせ」タブ枠 → `NoticesTab` 差し込み

### Task 6.1 — `notices.svelte.ts` localStorage 永続化

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\stores\notices.svelte.ts`

**Interfaces**
- 拡張: 初期化時に `localStorage.getItem('seen_notice_ids')` から `Set` 復元。`markSeen(id)` で Set 追加 + `localStorage.setItem` 同期。`markAllVisible()` で現 `items` 全て既読化 (タブを開いた瞬間に呼ぶ運用)。
- SSR 安全 (typeof window !== 'undefined' ガード)。

**Steps**

1. **(green) 編集。**

2. **(gate)** `npm run check` → 0 errors。

3. **(commit)** `git commit -m "feat(web): notices store に localStorage 既読永続化"`

---

### Task 6.2 — `NoticesTab.svelte` Linear 風 timeline

**Files**
- Create: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\feedback-hub\NoticesTab.svelte`
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\FeedbackHubDrawer.svelte` (お知らせタブの slot に `<NoticesTab />`)

**Interfaces**
- Consumes: `noticesStore.items`, `noticesStore.seenIds`, `noticesStore.markSeen`。
- レイアウト: spec §5.3 の Linear 式 timeline (日付ヘッダ「2026年6月28日」、エントリ、未読青ドット 6px、サブセクション見出し、箇条書き)。`markdown-it` 等を入れず、本文 `body_markdown` は MVP では `<pre style="white-space: pre-wrap">` で表示 (Sprint 9 で改善余地として記録)。
- mount 時に `noticesStore.load()` 呼出 → アイテム到着後、ユーザーが各エントリにマウスホバー (`onmouseenter`) で `markSeen` (Linear の挙動を参考)。

**Steps**

1. **(green) 実装。**

2. **(gate)** `npm run check && npm run build` → 0 errors / build。

3. **(commit)** `git commit -m "feat(web): NoticesTab (Linear 式 timeline + 既読管理)"`

---

### Sprint 6 視覚ゲート

1. 旗 → Drawer → 「お知らせ」タブで `2026-06-28 クラッシュレポート & フィードバックハブを公開しました` が表示される。日付ヘッダ「2026年6月28日」、サブセクション「新機能」見出しが視認できる。
2. 未読タイトル左に青ドット (6px)。ホバーすると次回ロード時に消える (localStorage `seen_notice_ids` 確認)。
3. Drawer タブ pill: お知らせ未読数が pill で出る (例「1」)、既読後は消える。
4. ヘッダ Megaphone 未読ドット: お知らせ未読 + crash pending の合算が 0 になると消える。
5. console.error 0 件。

PASS 後、Draft PR に push。

---

## Sprint 7 — 不具合タブ + 設定セクション + 初回オプトイン

**Scope:** Drawer の「不具合」タブ実装、設定画面に「クラッシュレポート」セクション追加、初回オプトイン Modal。

**Deliverables:**
- `apps/web/src/lib/components/feedback-hub/BugReportTab.svelte`
- `apps/web/src/lib/components/OptInDialog.svelte`
- `apps/web/src/lib/components/settings/CrashReportSection.svelte`
- `apps/web/src/routes/settings/+page.svelte` に section='crash' を追加
- `apps/web/src/routes/+layout.svelte` で OptIn 判定 (`crash_report.enabled === null` のとき表示)

### Task 7.1 — `BugReportTab.svelte`

**Files**
- Create: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\feedback-hub\BugReportTab.svelte`
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\FeedbackHubDrawer.svelte`

**Interfaces**
- Consumes: `crashReportsStore`。
- レイアウト: spec §5.4。冒頭説明文、「未送信のレポート」リスト (各項目: 例外型 / メッセージ / ファイルパス / 発生日時 + 「却下」「プレビュー →」ボタン)、下に「+ 新規報告を作成」 dashed-border カード。
- 「プレビュー →」→ `crashPreviewStore.openFor(crash)` (Task 5.7)。
- 「却下」→ `crashReportsStore.dismiss(id)`。
- 「+ 新規報告を作成」→ 空の `PendingCrash` 相当 (source="manual"、exception_type="Manual report") を作って `crashPreviewStore.openFor(...)`。**新規追加 backend endpoint**: `POST /api/crash/manual` body=`{summary: str}` → `CrashPendingItem` (collector.handle_manual を新設 → pending_store.save)。
  - Sprint 7 の補助タスクとして `core/crash_reporter/collector.py::handle_manual(summary: str) -> PendingCrash` を追加、`apps/api/routers/crash.py` に `POST /api/crash/manual` を追加、`test_crash_endpoints.py` に 1 ケース。

**Steps**

1. **(red) backend テスト。** `test_crash_endpoints.py` に「`POST /api/crash/manual` で `summary` を渡すと PendingCrash 1 件、source='manual' で保存される」。

2. **(run-fail)** → 404。

3. **(green) backend 実装。** collector + router。

4. **(green) frontend 実装。** BugReportTab + Drawer 結線。

5. **(gate)** `npm run check && npm run build` + `uv run pytest tests/integration/test_api/test_crash_endpoints.py -q`。

6. **(commit)** `git commit -m "feat: BugReportTab (未送信一覧 + 手動新規報告)"`

---

### Task 7.2 — `CrashReportSection.svelte` 設定セクション

**Files**
- Create: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\settings\CrashReportSection.svelte`
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\routes\settings\+page.svelte` (nav に「クラッシュレポート」追加 + section='crash' を扱う)
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\api\settings.ts` (`settingsApi.putCrashReport`)
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\stores\settings.svelte.ts` (`putCrashReport` メソッド)

**Interfaces**
- spec §5.8 のレイアウト: Megaphone + 「クラッシュレポート」見出し + NEW バッジ (初回のみ、`opted_in_at` が直近 7 日以内)。
- 行1: 「クラッシュレポート機能を有効にする」toggle ([[feedback_compact_ui_repurpose_affordance]] に従い既存 `AudioSettingsSection` の switch CSS を使い回す)
- 行2: 「エラー発生時に自動でダイアログを表示」toggle (auto_prompt)
- 行3: 「未送信レポート」 + 件数 badge + 「確認 →」(クリックで Drawer の不具合タブを open: `feedbackHubStore.open('bugs')`)
- 行4: 「サンプルレポートを見る」 + 「プレビューを開く」(モック PendingCrash で `crashPreviewStore.openFor`)

**Steps**

1. **(green) frontend 実装。** AudioSettingsSection の `.row` / `.switch` CSS を流用。

2. **(gate)** `npm run check && npm run build`。

3. **(commit)** `git commit -m "feat(settings): CrashReportSection を追加 (toggle + 未送信件数 + サンプル)"`

---

### Task 7.3 — `OptInDialog.svelte` 初回オプトイン

**Files**
- Create: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\OptInDialog.svelte`
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\routes\+layout.svelte` (mount 条件)

**Interfaces**
- 表示条件: `settingsStore.settings?.crash_report.enabled === null` (未決定) かつ `errorBoundary` がエラーをキャッチしようとした瞬間、または最初のセッション開始から 30 秒後。
- spec §5.9 レイアウト: タイトル「クラッシュレポート機能」、本文に「**送信前にプレビューが表示され、内容を確認・編集してから送信できます。** 報告は任意です。」、動作詳細は `<details>`、ボタン「後で決める」「有効にする」。
- 「後で決める」→ Dialog close のみ (`enabled` は `null` のまま、次回起動でも判定)。
- 「有効にする」→ `settingsApi.putCrashReport({enabled: true, auto_prompt: true, opted_in_at: new Date().toISOString()})`、設定 store reload、Dialog close、`pushToast('クラッシュレポートを有効にしました', 'success')`。
- **「常に無効」ボタンは出さない** (spec §5.9 明記)。

**Steps**

1. **(green) 実装。**

2. **(gate)** `npm run check && npm run build`。

3. **(commit)** `git commit -m "feat(web): OptInDialog (初回オプトイン、常に無効ボタンなし)"`

---

### Sprint 7 視覚ゲート

1. 設定画面 nav に「クラッシュレポート」追加、クリックで CrashReportSection 表示。toggle 切替→ `PUT /api/settings/crash-report` 200 + 「確認 →」で Drawer の不具合タブが直接開く。
2. `~/.notebook-ollama/settings.json` から `crash_report` セクションを削除し再起動 → 30 秒後に OptInDialog が出る (もしくは DevTools で `throw new Error()` でも出る)。「有効にする」で永続化 + 再起動後も `enabled=true` を維持。
3. 「+ 新規報告を作成」→ プレビュー画面 (空タイトル + 空 body) → 編集 → 「GitHubで開く」で manual ラベル付きの URL が開く。
4. console.error 0 件。
5. **縦肥大化チェック** ([[feedback_compact_ui_repurpose_affordance]]): 設定画面が縦に伸びすぎていないか。CrashReportSection は AudioSettingsSection と同じ row 密度であること。

PASS 後、Draft PR に push。

---

## Sprint 8 — ご意見タブ + スクショ (html2canvas)

**Scope:** 「ご意見」タブの完全実装 + `html2canvas` 依存追加 + スクショキャプチャ → クリップボード送付フロー。

**Deliverables:**
- `apps/web/package.json` に `html2canvas@^1.4.1` 追加 (`npm install`)
- `apps/web/src/lib/utils/screenshotCapture.ts`
- `apps/web/src/lib/components/feedback-hub/FeedbackTab.svelte`

### Task 8.1 — `html2canvas` 依存追加

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\package.json`
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\package-lock.json` (npm install で更新)

**Steps**

1. `cd E:\00_Git\10_NotebookOllama\apps\web && npm install html2canvas@^1.4.1 --save`

2. **(gate)** `npm run check && npm run build`。html2canvas は CommonJS / ESM 両対応、Vite で素直に動く。

3. **(commit)** `git add apps/web/package.json apps/web/package-lock.json && git commit -m "feat(web): html2canvas を依存追加 (スクショ機能用)"`

---

### Task 8.2 — `screenshotCapture.ts`

**Files**
- Create: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\utils\screenshotCapture.ts`

**Interfaces**
- Produces:
  ```ts
  import html2canvas from 'html2canvas';
  export async function captureCurrentView(): Promise<Blob> {
    const canvas = await html2canvas(document.body, {
      backgroundColor: '#ffffff',
      scale: 1, logging: false,
      ignoreElements: (el) => el.classList.contains('no-screenshot'),
    });
    return new Promise(resolve => canvas.toBlob(b => resolve(b!), 'image/png'));
  }
  export async function copyBlobToClipboard(blob: Blob): Promise<void> {
    // ClipboardItem は Chrome 76+ / Edge / 最新 Safari 対応。Firefox は要 flag。
    const item = new ClipboardItem({ [blob.type]: blob });
    await navigator.clipboard.write([item]);
  }
  ```
- Drawer 自身は `no-screenshot` クラスを root に持たせる (撮影中に drawer 自身が写り込まないように)。

**Steps**

1. **(green) 実装。** Drawer に `class="no-screenshot"` を追加 (Task 5.5 のファイル微修正)。

2. **(gate)** `npm run check && npm run build`。

3. **(commit)** `git commit -m "feat(web): screenshotCapture (html2canvas + ClipboardItem)"`

---

### Task 8.3 — `FeedbackTab.svelte`

**Files**
- Create: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\feedback-hub\FeedbackTab.svelte`
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\FeedbackHubDrawer.svelte`

**Interfaces**
- spec §5.5 の完全実装:
  - 種別チップ (機能要望 / 使いにくさ / 感想) + 各アイコン。
  - 本文 textarea (placeholder を category に応じて切替)。
  - 感情入力 Thumbs 3 段階 (ThumbsUp / Minus / ThumbsDown、Minus は spec deep-research 反映)。
  - スクショ添付エリア (dashed border カード + 「現在の画面を自動キャプチャ」ボタン + ドラッグ&ドロップ + ファイル選択)。
  - フッタ「キャンセル」「送信内容をプレビュー →」。
- 「現在の画面を自動キャプチャ」→ `captureCurrentView()` で Blob 取得 → サムネ表示 (object URL)。
- 「送信内容をプレビュー →」→ `feedbackHubApi.feedback({category, body, sentiment})` で `{url, ...}` 取得 → 確認 dialog (「以下の URL で Issue を作成します。送信前に GitHub 画面でスクショを手動でドラッグ&ドロップしてください」) + 「スクショをクリップボードにコピー」ボタン (`copyBlobToClipboard(blob)`) + 「GitHubで開く →」(`window.open(url, '_blank')`)。
- ファイル添付は MVP では Blob を内部に持つだけで送信せず、ユーザー手動添付に誘導 (spec §8.3 注意)。

**Steps**

1. **(green) 実装。**

2. **(gate)** `npm run check && npm run build`。

3. **(commit)** `git commit -m "feat(web): FeedbackTab (種別/本文/感情/スクショ + クリップボード経由送付)"`

---

### Sprint 8 視覚ゲート

1. ご意見タブで 3 種別チップが切り替わり、選択状態 (黒背景 / 白文字) が視認できる。
2. 感情ボタン 3 つ (Up / Minus / Down) が 44x44 で並ぶ。Minus がはっきり中立を示す (横向き thumb でない)。
3. 「現在の画面を自動キャプチャ」→ Drawer 自身が写り込まず、NotebookOllama の現画面のサムネが出る。
4. 「スクショをクリップボードにコピー」→ クリップボードにブラウザ画像が入る (OS の貼り付けテストで Image Viewer や Discord に貼り付け確認)。
5. 「GitHubで開く →」→ 新規タブに `github.com/.../issues/new?title=...&body=...&labels=feedback,category:feature` が開く。
6. console.error 0 件。
7. 縦肥大化チェック: Drawer 高さがブラウザ高さ 800px で全要素見える (スクロール 1 段は許容、2 段以上は NG)。

PASS 後、Draft PR に push。

---

## Sprint 9 — E2E + アイコンサイズ最終調整 + ドキュメント

**Scope:** Playwright E2E (spec §11.3 シナリオ 5 本)、Sprint 5 で繰り越したアイコンサイズの最終値決定、README / ISSUES の更新、CHANGELOG エントリ。

**Deliverables:**
- `apps/web/tests/e2e/feedback-hub.spec.ts` (5 シナリオ)
- `apps/web/src/lib/components/AppHeader.svelte` のアイコンサイズ確定 (Task 9.2)
- `data/notices.json` に「2026-06-28 launch」エントリ確定
- `README.md` (root) と `apps/web/README.md` への機能説明追加
- `docs/superpowers/plans/2026-06-28-crash-report-feedback-hub.md` の各 Sprint 末尾に「✅ 完了 (commit <sha>)」を追記 (このファイル自身を Sprint 9 中に更新)

### Task 9.1 — Playwright E2E 5 シナリオ

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\apps\web\playwright.config.ts` (必要に応じ baseURL / projects 調整 — 既存をなるべく流用)
- Create: `E:\00_Git\10_NotebookOllama\apps\web\tests\e2e\feedback-hub.spec.ts`

**Interfaces (テストシナリオ — spec §11.3 を厳密に踏襲)**

1. **シナリオ A**: バックエンド 500 → 即時モーダル → プレビュー → 「GitHubで開く」 → 新規タブ URL が `https://github.com/KawanoMomo/notebook-ollama/issues/new?` で始まる。
   - 実装: ルート `/api/_test/boom` を **テスト時のみ** 注入する仕組みは入れない。代わりに DevTools 経由の `window.dispatchEvent(new ErrorEvent(...))` を Playwright `evaluate` で起こす (errorBoundary の `'error'` リスナーをトリガ)。
2. **シナリオ B**: ヘッダ旗クリック → Drawer 表示 → タブ切替 (お知らせ / 不具合 / ご意見) 各 → 各タブのプレースホルダ or 充填要素が見える。
3. **シナリオ C**: お知らせ最初のエントリにホバー → リロード後に未読ドットが消えている (localStorage `seen_notice_ids` 確認は `context.localStorage()` で)。
4. **シナリオ D**: 設定画面で「クラッシュレポート機能を有効にする」を OFF → DevTools で error 発生 → 即時モーダルが出ない。
5. **シナリオ E**: 起動時 unclean shutdown 検知。
   - 実装: テスト先頭で `tmp_data_dir/running.lock` に偽 PID (`999999`) + `tmp_data_dir/logs/last-session.log` に擬似ログ 200 行を置く → `NOTEBOOK_OLLAMA_DATA_DIR=<tmp_data_dir>` で uvicorn を起動 (Playwright globalSetup) → `GET /api/crash/pending` で 1 件返ることをアサート。

**Steps**

1. **(red) テスト作成。** 上記 5 シナリオを 1 ファイル内に。

2. **(run-fail)** → 想定: シナリオ B/C/D は概ね pass、A/E は backend 起動条件次第で要調整。

3. **(green) 必要に応じ実装微調整。** 例: シナリオ A で errorBoundary が throttle で 2 回目を握りつぶす場合は、テストで `clearThrottle()` を import して呼ぶ抜け道を用意 (`__test_only__` 関数を `errorBoundary.ts` に追加)。

4. **(run-pass)** `cd apps/web && npx playwright test feedback-hub` → 5 passed。

5. **(commit)** `git commit -m "test(web): クラッシュレポート & フィードバックハブの E2E 5 シナリオ"`

---

### Task 9.2 — アイコンサイズ最終調整

**Files**
- Modify (場合により): `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\AppHeader.svelte`

**Steps**

1. **(視覚ゲート)** Evaluator が 16 / 18 / 20 px で並べてスクショ取り、決定値を 1 つ選ぶ。
2. **(green) 編集。** 既定 18px から変更が必要なら `<Megaphone size={N} />` を更新。
3. **(commit)** `git commit -m "ui: ヘッダ Megaphone のサイズを <N>px で確定 (歯車と並べた視覚バランス)"`

---

### Task 9.3 — README / CHANGELOG / ISSUES 更新

**Files**
- Modify: `E:\00_Git\10_NotebookOllama\README.md` (root) — 機能カード追加 (1 段落)
- Modify: `E:\00_Git\10_NotebookOllama\CLAUDE.md` — 「## 機能」セクションがあれば 1 行追加
- Modify (Create if absent): `E:\00_Git\10_NotebookOllama\docs\specs\2026-06-28-crash-report-feedback-hub-design.md` の `## 15. オープン項目` に「✅ Sprint 9 で確定: アイコンサイズ Npx」など Resolved を追記
- Modify: `E:\00_Git\10_NotebookOllama\docs\superpowers\plans\2026-06-28-crash-report-feedback-hub.md` (このファイル) の各 Sprint 末尾に `✅ 完了 (commit <sha>)` を追記。

**Steps**

1. **(green) 編集。** 各ファイルにそれぞれ 1〜3 行の追記。

2. **(commit)** `git commit -m "docs: crash-report-feedback-hub を README / spec オープン項目 / plan に反映"`

---

### Sprint 9 最終ゲート

1. `uv run pytest -q` → 全 pass。
2. `cd apps/web && npm run check` → 0 errors。
3. `cd apps/web && npm run build` → 成功。
4. `cd apps/web && npx playwright test feedback-hub` → 5 passed。
5. Sprint 5-8 の視覚ゲートを 1 度ずつ通し直し、final commit 状態でも崩れていないことを確認。
6. `git log --oneline master..HEAD` で commit 履歴を確認 (期待: 30〜45 commits)。
7. **Draft PR → Ready for Review** に変更。レビュー指摘吸収後 master へ merge。

---

## 関連ファイル (すべて絶対パス)

**仕様 (FIXED):**
- `E:\00_Git\10_NotebookOllama\docs\specs\2026-06-28-crash-report-feedback-hub-design.md`

**バックエンド新規:**
- `E:\00_Git\10_NotebookOllama\core\crash_reporter\__init__.py`
- `E:\00_Git\10_NotebookOllama\core\crash_reporter\redactor.py`
- `E:\00_Git\10_NotebookOllama\core\crash_reporter\fingerprint.py`
- `E:\00_Git\10_NotebookOllama\core\crash_reporter\hardware.py`
- `E:\00_Git\10_NotebookOllama\core\crash_reporter\pending_store.py`
- `E:\00_Git\10_NotebookOllama\core\crash_reporter\reported_store.py`
- `E:\00_Git\10_NotebookOllama\core\crash_reporter\formatter.py`
- `E:\00_Git\10_NotebookOllama\core\crash_reporter\prefill_url.py`
- `E:\00_Git\10_NotebookOllama\core\crash_reporter\collector.py`
- `E:\00_Git\10_NotebookOllama\core\crash_reporter\lifecycle.py`
- `E:\00_Git\10_NotebookOllama\core\crash_reporter\domain_errors.py`
- `E:\00_Git\10_NotebookOllama\core\feedback_hub\__init__.py`
- `E:\00_Git\10_NotebookOllama\core\feedback_hub\notice_store.py`
- `E:\00_Git\10_NotebookOllama\core\feedback_hub\feedback_formatter.py`
- `E:\00_Git\10_NotebookOllama\apps\api\routers\crash.py`
- `E:\00_Git\10_NotebookOllama\apps\api\routers\feedback_hub.py`
- `E:\00_Git\10_NotebookOllama\apps\api\schemas\crash.py`
- `E:\00_Git\10_NotebookOllama\apps\api\schemas\feedback_hub.py`
- `E:\00_Git\10_NotebookOllama\data\notices.json`

**バックエンド変更:**
- `E:\00_Git\10_NotebookOllama\core\config.py` (CrashReportSettings, crash_pending_dir)
- `E:\00_Git\10_NotebookOllama\core\exceptions.py` (DomainError, CRASH_REPORT_DISABLED)
- `E:\00_Git\10_NotebookOllama\core\settings_store.py` (crash_report 復元)
- `E:\00_Git\10_NotebookOllama\core\logging.py` (logs_dir 引数で last-session.log)
- `E:\00_Git\10_NotebookOllama\apps\api\schemas\settings.py` (CrashReportSettingsSchema)
- `E:\00_Git\10_NotebookOllama\apps\api\routers\settings.py` (get_settings + PUT /api/settings/crash-report)
- `E:\00_Git\10_NotebookOllama\apps\api\dependencies.py` (AppContext.crash_collector / notice_store_path)
- `E:\00_Git\10_NotebookOllama\apps\api\main.py` (router include + lifespan で collector.register + lifecycle)

**フロントエンド新規:**
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\api\crash.ts`
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\api\feedbackHub.ts`
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\stores\feedbackHub.svelte.ts`
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\stores\crashReports.svelte.ts`
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\stores\notices.svelte.ts`
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\stores\crashPreview.svelte.ts`
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\FeedbackHubDrawer.svelte`
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\CrashDetectionModal.svelte`
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\CrashPreviewDialog.svelte`
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\OptInDialog.svelte`
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\feedback-hub\NoticesTab.svelte`
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\feedback-hub\BugReportTab.svelte`
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\feedback-hub\FeedbackTab.svelte`
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\settings\CrashReportSection.svelte`
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\utils\errorBoundary.ts`
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\utils\screenshotCapture.ts`
- `E:\00_Git\10_NotebookOllama\apps\web\tests\e2e\feedback-hub.spec.ts`

**フロントエンド変更:**
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\api\types.ts` (CrashPendingItem 等)
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\api\settings.ts` (putCrashReport)
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\stores\settings.svelte.ts` (putCrashReport)
- `E:\00_Git\10_NotebookOllama\apps\web\src\lib\components\AppHeader.svelte` (Megaphone + 未読ドット)
- `E:\00_Git\10_NotebookOllama\apps\web\src\routes\+layout.svelte` (errorBoundary 起動 + Drawer/Modal/OptIn mount)
- `E:\00_Git\10_NotebookOllama\apps\web\src\routes\settings\+page.svelte` (nav に 'crash' 追加)
- `E:\00_Git\10_NotebookOllama\apps\web\package.json` (html2canvas 依存)
- `E:\00_Git\10_NotebookOllama\apps\web\package-lock.json`

**テスト新規:**
- `E:\00_Git\10_NotebookOllama\tests\unit\crash_reporter\__init__.py`
- `E:\00_Git\10_NotebookOllama\tests\unit\crash_reporter\test_constants.py`
- `E:\00_Git\10_NotebookOllama\tests\unit\crash_reporter\test_redactor.py`
- `E:\00_Git\10_NotebookOllama\tests\unit\crash_reporter\test_fingerprint.py`
- `E:\00_Git\10_NotebookOllama\tests\unit\crash_reporter\test_hardware.py`
- `E:\00_Git\10_NotebookOllama\tests\unit\crash_reporter\test_pending_store.py`
- `E:\00_Git\10_NotebookOllama\tests\unit\crash_reporter\test_reported_store.py`
- `E:\00_Git\10_NotebookOllama\tests\unit\crash_reporter\test_formatter.py`
- `E:\00_Git\10_NotebookOllama\tests\unit\crash_reporter\test_prefill_url.py`
- `E:\00_Git\10_NotebookOllama\tests\unit\crash_reporter\test_domain_error.py`
- `E:\00_Git\10_NotebookOllama\tests\unit\test_notice_store.py`
- `E:\00_Git\10_NotebookOllama\tests\integration\crash_reporter\__init__.py`
- `E:\00_Git\10_NotebookOllama\tests\integration\crash_reporter\test_collector.py`
- `E:\00_Git\10_NotebookOllama\tests\integration\crash_reporter\test_lifecycle.py`
- `E:\00_Git\10_NotebookOllama\tests\integration\test_api\test_crash_endpoints.py`
- `E:\00_Git\10_NotebookOllama\tests\integration\test_api\test_feedback_hub_endpoints.py`
- `E:\00_Git\10_NotebookOllama\tests\integration\test_api\test_settings_crash_report.py`
- `E:\00_Git\10_NotebookOllama\tests\integration\test_api\test_unclean_shutdown_detection.py`

**テスト変更:**
- `E:\00_Git\10_NotebookOllama\tests\unit\test_exceptions.py`
- `E:\00_Git\10_NotebookOllama\tests\unit\test_config.py`
- `E:\00_Git\10_NotebookOllama\tests\unit\test_audio_config_defaults.py`
- `E:\00_Git\10_NotebookOllama\tests\unit\test_logging.py`

---

## レビューチェックリスト (PR Ready for Review 前に必ず確認)

全項目 2026-07-02 最終QA (docs/eval/2026-07-02-crash-report-final-qa/) で確認済み。

- [x] [[feedback-no-data-guarantee-in-ui]]: UI のどこにも「以下のデータを送信します / 送信しません」リストが無いか (CrashDetectionModal / OptInDialog / CrashReportSection / FeedbackTab を grep)。→ grep 0件。CrashDetectionModal のコメントで明示的に不採用を記録済み。
- [x] [[feedback_compact_ui_repurpose_affordance]]: ヘッダ・設定画面・Drawer のどこも縦に肥大化していないか (Sprint 5/7/8 視覚ゲートの「縦肥大化チェック」項目を再実行)。→ 実機確認: ヘッダ56px不変・Megaphone/歯車とも34×34、Drawer 440px、CrashReportSection 559px (Audio設定1476pxと比べコンパクト)。
- [x] [[feedback_visual_verification]]: 全 GUI sprint で Evaluator スクショ証跡が PR に添付されているか。→ Sprint5-9 の docs/eval/2026-06-2*-feedback-hub-sprint* に加え、最終QAの docs/eval/2026-07-02-crash-report-final-qa/ を追加。
- [x] redactor が spec §6.2 のホワイトリストから外れていないか (Task 1.1 の `ALLOWED_LOG_FIELDS` が spec と一致)。→ 通す/通さないリストとも spec と完全一致 (denylist は HW識別子を追加で防御的に強化)。
- [x] 8KB URL 制限が極端入力でも `MAX_URL_LEN` 以下に収まるか (Task 2.4 のテストで保証)。→ `MAX_URL_LEN=7000`、境界値・5万字入力含む test_prefill_url.py 42件PASS。
- [x] `~/.notebook-ollama/reported.txt` / `crash-pending/*.json` / `running.lock` / `logs/last-session.log` の生成位置が `config.data_dir` 配下に統一されているか。→ core/config.py で全パスが `data_dir` 起点と確認。
- [x] origin remote と `REPO_SLUG` が一致するか (`KawanoMomo/notebook-ollama`)。→ 一致確認。
- [x] `master` ブランチに直接 commit していないか (`git log --oneline master..HEAD` でこの PR の全 commit が見える状態)。→ 全14 commit が feature branch上のみ。
- [x] console.error が全シナリオで 0 件か (Playwright E2E + 手動 DevTools)。→ 初回検証で `apps/web/src/lib/api/client.ts` の実バグ (非2xx `{detail}` 応答での TypeError) を発見・修正 (TDD, tests/unit/api-client.test.ts)。再検証で全シナリオ console.error 0件・PASS。

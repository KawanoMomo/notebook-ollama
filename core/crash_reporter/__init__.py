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
    # ホスト/HW 識別子 (機器固有 PII)。ALLOWED_LOG_FIELDS で弾かれるが、
    # 明示的に禁止リスト入りさせて再帰検出 (ネストされたケース) にも引っかけ、
    # 起動時のホスト情報リークを防ぐ。
    "ip", "mac", "hostname", "serial",
})
"""ホワイトリスト方式の念のための明示禁止リスト。"""

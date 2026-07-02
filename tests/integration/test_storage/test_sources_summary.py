"""sources テーブルの summary / summary_status 列のマイグレーションと CRUD。

設計仕様: docs/specs/2026-06-25-source-guide-design.md §4.4
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.exceptions import AppError, ErrorCode
from core.storage import sources_repo
from core.storage.database import migrate
from core.storage.migrations import run_summary_migration
from core.storage.sources_repo import SummaryStatus


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    migrate(c)
    return c


def _nb(conn: sqlite3.Connection) -> str:
    from core.storage import notebooks_repo

    return notebooks_repo.create_notebook(conn, name="N").id


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


# --- schema / migration ---


def test_fresh_schema_has_summary_columns(conn):
    cols = _columns(conn, "sources")
    assert "summary" in cols
    assert "summary_status" in cols


def test_run_summary_migration_is_idempotent(conn):
    # 既に migrate() で適用済み。二回呼んでも例外を出さず冪等。
    run_summary_migration(conn)
    run_summary_migration(conn)
    cols = _columns(conn, "sources")
    assert "summary" in cols
    assert "summary_status" in cols


def test_run_summary_migration_adds_columns_to_legacy_db(tmp_path: Path):
    """summary カラムがない既存 DB に対しても ALTER TABLE で追加される。"""
    db = tmp_path / "legacy.sqlite3"
    c = sqlite3.connect(str(db))
    c.row_factory = sqlite3.Row
    # 旧スキーマ相当(summary 列なし)を手動で作る
    c.executescript(
        """
        CREATE TABLE notebooks (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT,
            default_model TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE sources (
            id TEXT PRIMARY KEY, notebook_id TEXT NOT NULL REFERENCES notebooks(id),
            kind TEXT NOT NULL, title TEXT, origin TEXT, content_hash TEXT,
            status TEXT NOT NULL, error_msg TEXT, bytes INTEGER, page_count INTEGER,
            chunk_count INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        """
    )
    assert "summary" not in _columns(c, "sources")
    run_summary_migration(c)
    cols = _columns(c, "sources")
    assert "summary" in cols
    assert "summary_status" in cols
    c.close()


# --- repo CRUD ---


def test_create_source_defaults_summary_to_none(conn):
    nb = _nb(conn)
    src = sources_repo.create_source(conn, notebook_id=nb, kind="markdown")
    assert src.summary is None
    assert src.summary_status is None


def test_update_source_summary_status_generating(conn):
    nb = _nb(conn)
    src = sources_repo.create_source(conn, notebook_id=nb, kind="markdown")
    updated = sources_repo.update_source_summary_status(
        conn, src.id, status=SummaryStatus.GENERATING
    )
    assert updated.summary_status == SummaryStatus.GENERATING
    assert updated.summary is None
    assert updated.updated_at >= src.updated_at


def test_update_source_summary_sets_text_and_ready(conn):
    nb = _nb(conn)
    src = sources_repo.create_source(conn, notebook_id=nb, kind="markdown")
    sources_repo.update_source_summary_status(
        conn, src.id, status=SummaryStatus.GENERATING
    )
    updated = sources_repo.update_source_summary(
        conn, src.id, summary="3行で要約しました。"
    )
    # update_source_summary は同時に status=ready をセット
    assert updated.summary == "3行で要約しました。"
    assert updated.summary_status == SummaryStatus.READY


def test_update_source_summary_status_error_keeps_existing_summary(conn):
    """error への遷移は既存の summary を消さない(古い要約を保持する選択もあり得るが、
    仕様上は 3 回失敗で error なので summary はそもそも未保存。ここでは消さないことを担保)。"""
    nb = _nb(conn)
    src = sources_repo.create_source(conn, notebook_id=nb, kind="markdown")
    sources_repo.update_source_summary(conn, src.id, summary="既存要約")
    updated = sources_repo.update_source_summary_status(
        conn, src.id, status=SummaryStatus.ERROR
    )
    assert updated.summary == "既存要約"
    assert updated.summary_status == SummaryStatus.ERROR


def test_update_source_summary_status_unknown_id_raises_not_found(conn):
    with pytest.raises(AppError) as ei:
        sources_repo.update_source_summary_status(
            conn, "does-not-exist", status=SummaryStatus.GENERATING
        )
    assert ei.value.code == ErrorCode.STORAGE_NOT_FOUND


def test_update_source_summary_unknown_id_raises_not_found(conn):
    with pytest.raises(AppError) as ei:
        sources_repo.update_source_summary(conn, "does-not-exist", summary="x")
    assert ei.value.code == ErrorCode.STORAGE_NOT_FOUND

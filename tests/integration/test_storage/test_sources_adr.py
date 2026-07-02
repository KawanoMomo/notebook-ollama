"""sources テーブルの adr_* 列のマイグレーションと CRUD。

設計: docs/specs/2026-06-26-meeting-adr-templates.md
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.exceptions import AppError, ErrorCode
from core.storage import sources_repo
from core.storage.database import migrate
from core.storage.migrations import run_adr_migration
from core.storage.sources_repo import AdrStatus


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


def test_fresh_schema_has_adr_columns(conn):
    cols = _columns(conn, "sources")
    for c in ("adr_draft", "adr_status", "adr_template", "adr_confidence", "adr_generated_at"):
        assert c in cols, c


def test_run_adr_migration_is_idempotent(conn):
    run_adr_migration(conn)
    run_adr_migration(conn)
    cols = _columns(conn, "sources")
    expected = {"adr_draft", "adr_status", "adr_template", "adr_confidence", "adr_generated_at"}
    assert expected.issubset(cols)


def test_run_adr_migration_adds_columns_to_legacy_db(tmp_path: Path):
    """adr 列の無い既存 DB に対しても ALTER TABLE で追加される。"""
    db = tmp_path / "legacy.sqlite3"
    c = sqlite3.connect(str(db))
    c.row_factory = sqlite3.Row
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
            chunk_count INTEGER, summary TEXT, summary_status TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        """
    )
    assert "adr_draft" not in _columns(c, "sources")
    run_adr_migration(c)
    cols = _columns(c, "sources")
    assert "adr_draft" in cols
    assert "adr_status" in cols
    c.close()


def test_create_source_defaults_adr_to_none(conn):
    nb = _nb(conn)
    src = sources_repo.create_source(conn, notebook_id=nb, kind="markdown")
    assert src.adr_draft is None
    assert src.adr_status is None
    assert src.adr_template is None
    assert src.adr_confidence is None
    assert src.adr_generated_at is None


def test_update_source_adr_status_generating(conn):
    nb = _nb(conn)
    src = sources_repo.create_source(conn, notebook_id=nb, kind="markdown")
    updated = sources_repo.update_source_adr_status(
        conn, src.id, status=AdrStatus.GENERATING
    )
    assert updated.adr_status == AdrStatus.GENERATING


def test_update_source_adr_sets_markdown_template_confidence_and_ready(conn):
    nb = _nb(conn)
    src = sources_repo.create_source(conn, notebook_id=nb, kind="markdown")
    sources_repo.update_source_adr_status(conn, src.id, status=AdrStatus.GENERATING)
    updated = sources_repo.update_source_adr(
        conn,
        src.id,
        draft="# ADR-001\n\n## Context\n...",
        template="madr",
        confidence="high",
    )
    assert updated.adr_status == AdrStatus.READY
    assert updated.adr_template == "madr"
    assert updated.adr_confidence == "high"
    assert updated.adr_draft is not None
    assert "ADR-001" in updated.adr_draft
    assert updated.adr_generated_at is not None


def test_update_source_adr_skipped_persists_reason(conn):
    nb = _nb(conn)
    src = sources_repo.create_source(conn, notebook_id=nb, kind="markdown")
    updated = sources_repo.update_source_adr_skipped(
        conn,
        src.id,
        reason="No decision detected",
        evidence="The text contains only status updates.",
    )
    assert updated.adr_status == AdrStatus.SKIPPED
    # reason は draft に JSON 一行で格納される(仕様)。中身に reason/evidence を含む。
    assert updated.adr_draft is not None
    assert "No decision detected" in updated.adr_draft


def test_update_source_adr_status_unknown_id_raises_not_found(conn):
    with pytest.raises(AppError) as ei:
        sources_repo.update_source_adr_status(
            conn, "does-not-exist", status=AdrStatus.GENERATING
        )
    assert ei.value.code == ErrorCode.STORAGE_NOT_FOUND

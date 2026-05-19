from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from core.exceptions import AppError, ErrorCode
from core.ids import new_id


class SourceStatus(StrEnum):
    PENDING = "pending"
    PARSING = "parsing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    READY = "ready"
    ERROR = "error"


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class SourceRecord:
    id: str
    notebook_id: str
    kind: str
    title: str | None
    origin: str | None
    content_hash: str | None
    status: SourceStatus
    error_msg: str | None
    bytes: int | None
    page_count: int | None
    chunk_count: int | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> SourceRecord:
        return cls(
            id=row["id"],
            notebook_id=row["notebook_id"],
            kind=row["kind"],
            title=row["title"],
            origin=row["origin"],
            content_hash=row["content_hash"],
            status=SourceStatus(row["status"]),
            error_msg=row["error_msg"],
            bytes=row["bytes"],
            page_count=row["page_count"],
            chunk_count=row["chunk_count"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def create_source(
    conn: sqlite3.Connection,
    *,
    notebook_id: str,
    kind: str,
    origin: str | None = None,
    title: str | None = None,
    content_hash: str | None = None,
    bytes_: int | None = None,
) -> SourceRecord:
    now = _now()
    rec_id = new_id()
    conn.execute(
        "INSERT INTO sources(id, notebook_id, kind, title, origin, content_hash, status, "
        "bytes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            rec_id,
            notebook_id,
            kind,
            title,
            origin,
            content_hash,
            SourceStatus.PENDING.value,
            bytes_,
            now,
            now,
        ),
    )
    return get_source(conn, rec_id)


def get_source(conn: sqlite3.Connection, source_id: str) -> SourceRecord:
    row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    if row is None:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, f"source {source_id} not found")
    return SourceRecord.from_row(row)


def list_sources(conn: sqlite3.Connection, *, notebook_id: str) -> list[SourceRecord]:
    rows = conn.execute(
        "SELECT * FROM sources WHERE notebook_id = ? ORDER BY created_at DESC",
        (notebook_id,),
    ).fetchall()
    return [SourceRecord.from_row(r) for r in rows]


def update_source_status(
    conn: sqlite3.Connection,
    source_id: str,
    *,
    status: SourceStatus,
    error_msg: str | None = None,
    page_count: int | None = None,
    chunk_count: int | None = None,
    title: str | None = None,
) -> SourceRecord:
    existing = get_source(conn, source_id)
    conn.execute(
        "UPDATE sources SET status=?, error_msg=?, page_count=?, chunk_count=?, "
        "title=COALESCE(?, title), updated_at=? WHERE id=?",
        (
            status.value,
            error_msg,
            page_count if page_count is not None else existing.page_count,
            chunk_count if chunk_count is not None else existing.chunk_count,
            title,
            _now(),
            source_id,
        ),
    )
    return get_source(conn, source_id)


def upsert_dedupe(
    conn: sqlite3.Connection,
    *,
    notebook_id: str,
    kind: str,
    content_hash: str,
    origin: str | None = None,
    title: str | None = None,
    bytes_: int | None = None,
) -> tuple[SourceRecord, bool]:
    """Return (record, was_new). If content_hash already exists in notebook, return existing."""
    row = conn.execute(
        "SELECT * FROM sources WHERE notebook_id = ? AND content_hash = ?",
        (notebook_id, content_hash),
    ).fetchone()
    if row is not None:
        return SourceRecord.from_row(row), False
    return (
        create_source(
            conn,
            notebook_id=notebook_id,
            kind=kind,
            origin=origin,
            title=title,
            content_hash=content_hash,
            bytes_=bytes_,
        ),
        True,
    )

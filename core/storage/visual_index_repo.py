from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class VisualIndexMeta:
    notebook_id: str
    embedding_model: str
    built_at: str


def upsert_meta(conn: sqlite3.Connection, meta: VisualIndexMeta) -> None:
    conn.execute(
        "INSERT INTO visual_index_meta(notebook_id, embedding_model, built_at) "
        "VALUES (?, ?, ?) ON CONFLICT(notebook_id) DO UPDATE SET "
        "embedding_model=excluded.embedding_model, built_at=excluded.built_at",
        (meta.notebook_id, meta.embedding_model, meta.built_at),
    )


def get_meta(conn: sqlite3.Connection, notebook_id: str) -> VisualIndexMeta | None:
    row = conn.execute(
        "SELECT * FROM visual_index_meta WHERE notebook_id = ?", (notebook_id,)
    ).fetchone()
    if row is None:
        return None
    return VisualIndexMeta(
        notebook_id=row["notebook_id"],
        embedding_model=row["embedding_model"],
        built_at=row["built_at"],
    )


def delete_meta(conn: sqlite3.Connection, notebook_id: str) -> None:
    conn.execute("DELETE FROM visual_index_meta WHERE notebook_id = ?", (notebook_id,))
    conn.execute("DELETE FROM visual_index_sources WHERE notebook_id = ?", (notebook_id,))


def mark_source_indexed(
    conn: sqlite3.Connection, *, notebook_id: str, source_id: str, page_count: int, built_at: str
) -> None:
    conn.execute(
        "INSERT INTO visual_index_sources(source_id, notebook_id, page_count, built_at) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(source_id) DO UPDATE SET "
        "page_count=excluded.page_count, built_at=excluded.built_at",
        (source_id, notebook_id, page_count, built_at),
    )


def list_indexed_source_ids(conn: sqlite3.Connection, notebook_id: str) -> set[str]:
    rows = conn.execute(
        "SELECT source_id FROM visual_index_sources WHERE notebook_id = ?", (notebook_id,)
    ).fetchall()
    return {r["source_id"] for r in rows}


def delete_indexed_source(conn: sqlite3.Connection, source_id: str) -> None:
    conn.execute("DELETE FROM visual_index_sources WHERE source_id = ?", (source_id,))

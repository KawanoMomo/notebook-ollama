from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass
class ChunkRecord:
    id: str
    source_id: str
    notebook_id: str
    ord: int
    page: int | None
    heading_path: str | None
    text: str
    token_count: int
    start_ms: int | None = None
    end_ms: int | None = None
    speaker: str | None = None
    kind: str = "text"

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> ChunkRecord:
        keys = row.keys()
        return cls(
            id=row["id"],
            source_id=row["source_id"],
            notebook_id=row["notebook_id"],
            ord=row["ord"],
            page=row["page"],
            heading_path=row["heading_path"],
            text=row["text"],
            token_count=row["token_count"],
            start_ms=row["start_ms"] if "start_ms" in keys else None,
            end_ms=row["end_ms"] if "end_ms" in keys else None,
            speaker=row["speaker"] if "speaker" in keys else None,
            kind=row["kind"] if "kind" in keys else "text",
        )


def insert_chunks(conn: sqlite3.Connection, chunks: Iterable[ChunkRecord]) -> None:
    rows = [
        (c.id, c.source_id, c.notebook_id, c.ord, c.page, c.heading_path,
         c.text, c.token_count, c.start_ms, c.end_ms, c.speaker, c.kind)
        for c in chunks
    ]
    conn.executemany(
        "INSERT INTO chunks(id, source_id, notebook_id, ord, page, heading_path, "
        "text, token_count, start_ms, end_ms, speaker, kind) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )


def get_chunks_by_ids(conn: sqlite3.Connection, ids: list[str]) -> list[ChunkRecord]:
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    # S608 is a false positive here: `placeholders` is only the literal
    # "?,?,...,?" built from len(ids); the ids themselves are still bound as
    # parameters (second arg to execute), never interpolated.
    rows = conn.execute(
        f"SELECT * FROM chunks WHERE id IN ({placeholders})",  # noqa: S608
        ids,
    ).fetchall()
    by_id = {row["id"]: ChunkRecord.from_row(row) for row in rows}
    return [by_id[i] for i in ids if i in by_id]


def list_chunks_for_source(conn: sqlite3.Connection, source_id: str) -> list[ChunkRecord]:
    rows = conn.execute(
        "SELECT * FROM chunks WHERE source_id = ? ORDER BY ord ASC", (source_id,)
    ).fetchall()
    return [ChunkRecord.from_row(row) for row in rows]


def delete_chunks_for_source(conn: sqlite3.Connection, source_id: str) -> None:
    conn.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))


def list_text_chunks_for_page(
    conn: sqlite3.Connection, source_id: str, page: int, limit: int
) -> list[ChunkRecord]:
    """視覚ページヒット展開用: そのページの本文チャンク先頭N件(ord昇順)。"""
    rows = conn.execute(
        "SELECT * FROM chunks WHERE source_id = ? AND page = ? AND kind = 'text' "
        "ORDER BY ord LIMIT ?",
        (source_id, page, limit),
    ).fetchall()
    return [ChunkRecord.from_row(r) for r in rows]


def rename_speaker_in_source(
    conn: sqlite3.Connection, source_id: str, from_label: str, to_label: str
) -> int:
    """Rename all chunks of ``from_label`` to ``to_label`` within one source.

    Scope is within-source only (M4). Returns the number of rows updated.
    """
    cur = conn.execute(
        "UPDATE chunks SET speaker = ? WHERE source_id = ? AND speaker = ?",
        (to_label, source_id, from_label),
    )
    return cur.rowcount

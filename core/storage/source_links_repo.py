from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from core.exceptions import AppError, ErrorCode
from core.ids import new_id


@dataclass
class SourceLinkRecord:
    id: str
    notebook_id: str
    parent_source_id: str
    child_source_id: str
    relation: str  # 'presentation' | 'manual'
    meta: dict | None
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "SourceLinkRecord":
        return cls(
            id=row["id"],
            notebook_id=row["notebook_id"],
            parent_source_id=row["parent_source_id"],
            child_source_id=row["child_source_id"],
            relation=row["relation"],
            meta=json.loads(row["meta"]) if row["meta"] else None,
            created_at=row["created_at"],
        )


def get_parent_link(conn: sqlite3.Connection, child_source_id: str) -> SourceLinkRecord | None:
    row = conn.execute(
        "SELECT * FROM source_links WHERE child_source_id = ?", (child_source_id,)
    ).fetchone()
    return SourceLinkRecord.from_row(row) if row else None


def list_links_for_notebook(conn: sqlite3.Connection, notebook_id: str) -> list[SourceLinkRecord]:
    rows = conn.execute(
        "SELECT * FROM source_links WHERE notebook_id = ? ORDER BY created_at",
        (notebook_id,),
    ).fetchall()
    return [SourceLinkRecord.from_row(r) for r in rows]


def list_child_links(conn: sqlite3.Connection, parent_source_id: str) -> list[SourceLinkRecord]:
    rows = conn.execute(
        "SELECT * FROM source_links WHERE parent_source_id = ? ORDER BY created_at",
        (parent_source_id,),
    ).fetchall()
    return [SourceLinkRecord.from_row(r) for r in rows]


def _would_cycle(conn: sqlite3.Connection, parent_source_id: str, child_source_id: str) -> bool:
    """child を parent の子にしたとき循環するか。parent の祖先を辿って child が現れたら循環。"""
    seen: set[str] = set()
    cur: str | None = parent_source_id
    while cur is not None and cur not in seen:
        if cur == child_source_id:
            return True
        seen.add(cur)
        link = get_parent_link(conn, cur)
        cur = link.parent_source_id if link else None
    return False


def set_parent(
    conn: sqlite3.Connection,
    *,
    notebook_id: str,
    parent_source_id: str,
    child_source_id: str,
    relation: str,
    meta: dict | None = None,
) -> SourceLinkRecord:
    """子の親を設定する(既存の親リンクは置換)。自己リンク・循環は拒否。"""
    if parent_source_id == child_source_id:
        raise AppError(ErrorCode.INPUT_INVALID, "self link is not allowed")
    if _would_cycle(conn, parent_source_id, child_source_id):
        raise AppError(ErrorCode.INPUT_INVALID, "cyclic link is not allowed")
    conn.execute("DELETE FROM source_links WHERE child_source_id = ?", (child_source_id,))
    link_id = new_id()
    conn.execute(
        "INSERT INTO source_links (id, notebook_id, parent_source_id, child_source_id,"
        " relation, meta) VALUES (?, ?, ?, ?, ?, ?)",
        (
            link_id,
            notebook_id,
            parent_source_id,
            child_source_id,
            relation,
            json.dumps(meta, ensure_ascii=False) if meta is not None else None,
        ),
    )
    row = conn.execute("SELECT * FROM source_links WHERE id = ?", (link_id,)).fetchone()
    return SourceLinkRecord.from_row(row)


def remove_parent(conn: sqlite3.Connection, child_source_id: str) -> None:
    conn.execute("DELETE FROM source_links WHERE child_source_id = ?", (child_source_id,))

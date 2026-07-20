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


_VALID_RELATIONS = ("presentation", "manual")  # v1 の2値。将来種別はここに追加


def _require_source_in_notebook(
    conn: sqlite3.Connection, source_id: str, notebook_id: str
) -> None:
    row = conn.execute(
        "SELECT notebook_id FROM sources WHERE id = ?", (source_id,)
    ).fetchone()
    if row is None:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, f"source {source_id} not found")
    if row["notebook_id"] != notebook_id:
        raise AppError(ErrorCode.INPUT_INVALID, "source belongs to a different notebook")


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
    """子の親を設定する(既存の親リンクは置換)。自己リンク・循環は拒否。

    接続は autocommit(isolation_level=None)のため、DELETE+INSERT を明示
    トランザクションで囲む。途中失敗時は既存リンクを保持したまま巻き戻す。
    """
    if parent_source_id == child_source_id:
        raise AppError(ErrorCode.INPUT_INVALID, "self link is not allowed")
    if relation not in _VALID_RELATIONS:
        raise AppError(ErrorCode.INPUT_INVALID, f"unknown relation: {relation}")
    _require_source_in_notebook(conn, parent_source_id, notebook_id)
    _require_source_in_notebook(conn, child_source_id, notebook_id)
    if _would_cycle(conn, parent_source_id, child_source_id):
        raise AppError(ErrorCode.INPUT_INVALID, "cyclic link is not allowed")
    link_id = new_id()
    conn.execute("BEGIN")
    try:
        conn.execute(
            "DELETE FROM source_links WHERE child_source_id = ?", (child_source_id,)
        )
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
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    row = conn.execute("SELECT * FROM source_links WHERE id = ?", (link_id,)).fetchone()
    return SourceLinkRecord.from_row(row)


def remove_parent(conn: sqlite3.Connection, child_source_id: str) -> None:
    conn.execute("DELETE FROM source_links WHERE child_source_id = ?", (child_source_id,))

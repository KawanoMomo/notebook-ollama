from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from core.exceptions import AppError, ErrorCode
from core.ids import new_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ConversationRecord:
    id: str
    notebook_id: str
    title: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ConversationRecord":
        return cls(
            id=row["id"],
            notebook_id=row["notebook_id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def create_conversation(
    conn: sqlite3.Connection,
    *,
    notebook_id: str,
    title: str | None = None,
) -> ConversationRecord:
    cid = new_id()
    now = _now()
    conn.execute(
        "INSERT INTO conversations(id, notebook_id, title, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (cid, notebook_id, title, now, now),
    )
    return get_conversation(conn, cid)


def get_conversation(conn: sqlite3.Connection, conv_id: str) -> ConversationRecord:
    row = conn.execute(
        "SELECT * FROM conversations WHERE id = ?", (conv_id,)
    ).fetchone()
    if row is None:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, f"conversation {conv_id} not found")
    return ConversationRecord.from_row(row)


def list_conversations(
    conn: sqlite3.Connection, *, notebook_id: str
) -> list[ConversationRecord]:
    rows = conn.execute(
        "SELECT * FROM conversations WHERE notebook_id = ? ORDER BY updated_at DESC",
        (notebook_id,),
    ).fetchall()
    return [ConversationRecord.from_row(r) for r in rows]


def touch_conversation(conn: sqlite3.Connection, conv_id: str) -> None:
    conn.execute(
        "UPDATE conversations SET updated_at=? WHERE id=?", (_now(), conv_id)
    )

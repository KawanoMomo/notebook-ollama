from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.ids import new_id


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class MessageRecord:
    id: str
    conversation_id: str
    role: str
    content: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    model: str | None = None
    created_at: str = ""

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> MessageRecord:
        return cls(
            id=row["id"],
            conversation_id=row["conversation_id"],
            role=row["role"],
            content=row["content"],
            citations=json.loads(row["citations"]) if row["citations"] else [],
            model=row["model"],
            created_at=row["created_at"],
        )


def append_message(
    conn: sqlite3.Connection,
    *,
    conversation_id: str,
    role: str,
    content: str,
    citations: list[dict[str, Any]] | None = None,
    model: str | None = None,
) -> MessageRecord:
    mid = new_id()
    now = _now()
    conn.execute(
        "INSERT INTO messages(id, conversation_id, role, content, citations, model, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            mid,
            conversation_id,
            role,
            content,
            json.dumps(citations) if citations else None,
            model,
            now,
        ),
    )
    conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id))
    row = conn.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
    return MessageRecord.from_row(row)


def list_messages(conn: sqlite3.Connection, *, conversation_id: str) -> list[MessageRecord]:
    rows = conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
        (conversation_id,),
    ).fetchall()
    return [MessageRecord.from_row(r) for r in rows]

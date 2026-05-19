from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from core.exceptions import AppError, ErrorCode
from core.ids import new_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class NotebookRecord:
    id: str
    name: str
    description: str | None
    default_model: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "NotebookRecord":
        return cls(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            default_model=row["default_model"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def create_notebook(
    conn: sqlite3.Connection,
    *,
    name: str,
    description: str | None = None,
    default_model: str | None = None,
) -> NotebookRecord:
    now = _now()
    rec = NotebookRecord(
        id=new_id(),
        name=name,
        description=description,
        default_model=default_model,
        created_at=now,
        updated_at=now,
    )
    conn.execute(
        "INSERT INTO notebooks(id, name, description, default_model, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (rec.id, rec.name, rec.description, rec.default_model, rec.created_at, rec.updated_at),
    )
    return rec


def get_notebook(conn: sqlite3.Connection, notebook_id: str) -> NotebookRecord:
    row = conn.execute(
        "SELECT * FROM notebooks WHERE id = ?", (notebook_id,)
    ).fetchone()
    if row is None:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, f"notebook {notebook_id} not found")
    return NotebookRecord.from_row(row)


def list_notebooks(conn: sqlite3.Connection) -> list[NotebookRecord]:
    rows = conn.execute(
        "SELECT * FROM notebooks ORDER BY updated_at DESC, id DESC"
    ).fetchall()
    return [NotebookRecord.from_row(r) for r in rows]


def update_notebook(
    conn: sqlite3.Connection,
    notebook_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    default_model: str | None = None,
) -> NotebookRecord:
    existing = get_notebook(conn, notebook_id)
    new_name = name if name is not None else existing.name
    new_desc = description if description is not None else existing.description
    new_model = default_model if default_model is not None else existing.default_model
    now = _now()
    conn.execute(
        "UPDATE notebooks SET name=?, description=?, default_model=?, updated_at=? WHERE id=?",
        (new_name, new_desc, new_model, now, notebook_id),
    )
    return get_notebook(conn, notebook_id)


def delete_notebook(conn: sqlite3.Connection, notebook_id: str) -> None:
    get_notebook(conn, notebook_id)
    conn.execute("DELETE FROM notebooks WHERE id = ?", (notebook_id,))

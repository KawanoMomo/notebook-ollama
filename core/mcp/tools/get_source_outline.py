from __future__ import annotations

import sqlite3
from typing import Any

from core.storage import sources_repo


def get_source_outline_tool(*, conn: sqlite3.Connection, source_id: str) -> dict[str, Any]:
    src = sources_repo.get_source(conn, source_id)
    rows = conn.execute(
        "SELECT DISTINCT heading_path, page FROM chunks WHERE source_id = ? ORDER BY ord ASC",
        (source_id,),
    ).fetchall()
    headings = [
        {"heading_path": row["heading_path"], "page": row["page"]}
        for row in rows
        if row["heading_path"] or row["page"] is not None
    ]
    return {
        "source_id": src.id,
        "title": src.title,
        "kind": src.kind,
        "page_count": src.page_count,
        "headings": headings,
    }

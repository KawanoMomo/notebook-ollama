from __future__ import annotations

import sqlite3
from typing import Any

from core.storage import notebooks_repo, sources_repo


def list_notebooks_tool(conn: sqlite3.Connection) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for nb in notebooks_repo.list_notebooks(conn):
        srcs = sources_repo.list_sources(conn, notebook_id=nb.id)
        items.append(
            {
                "id": nb.id,
                "name": nb.name,
                "description": nb.description,
                "default_model": nb.default_model,
                "source_count": len(srcs),
            }
        )
    return {"notebooks": items}

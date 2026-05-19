from __future__ import annotations

import sqlite3
from typing import Any, Protocol

from core.ollama.models_info import classify_recommendation, parse_context_window
from core.storage import notebooks_repo


class _ClientLike(Protocol):
    async def list_tags(self) -> list[dict[str, Any]]: ...
    async def show(self, model: str) -> dict[str, Any]: ...


async def list_models_tool(*, conn: sqlite3.Connection, client: _ClientLike) -> dict[str, Any]:
    tags = await client.list_tags()
    models: list[dict[str, Any]] = []
    for tag in tags:
        name = tag["name"]
        details = tag.get("details", {}) or {}
        show = await client.show(name)
        ctx_window = parse_context_window(show.get("parameters", ""))
        models.append(
            {
                "name": name,
                "size_bytes": tag.get("size"),
                "context_window": ctx_window,
                "modified_at": tag.get("modified_at"),
                "recommended_for": classify_recommendation(
                    name=name,
                    family=details.get("family", ""),
                    parameter_size=details.get("parameter_size", ""),
                    context_window=ctx_window,
                ),
            }
        )
    defaults = [
        {"notebook_id": n.id, "name": n.name, "default_model": n.default_model}
        for n in notebooks_repo.list_notebooks(conn)
    ]
    return {"models": models, "defaults_by_notebook": defaults}

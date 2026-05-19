from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from core.ollama.client import OllamaClient
from core.ollama.models_info import classify_recommendation, parse_context_window
from core.storage import notebooks_repo

router = APIRouter(prefix="/api", tags=["models"])


@router.get("/models")
async def list_models(request: Request) -> dict[str, Any]:
    ctx = request.app.state.ctx
    client = OllamaClient(
        endpoint=ctx.config.ollama.endpoint,
        timeout=ctx.config.ollama.request_timeout_seconds,
    )
    tags = await client.list_tags()
    models: list[dict[str, Any]] = []
    for tag in tags:
        name = tag["name"]
        details = tag.get("details", {}) or {}
        show = await client.show(name)
        params_str = show.get("parameters", "")
        ctx_window = parse_context_window(params_str)
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
    notebooks = notebooks_repo.list_notebooks(ctx.conn)
    defaults = [
        {"notebook_id": n.id, "name": n.name, "default_model": n.default_model} for n in notebooks
    ]
    return {"models": models, "defaults_by_notebook": defaults}

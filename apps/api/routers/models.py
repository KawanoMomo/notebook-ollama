from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from core.ollama.client import OllamaClient
from core.ollama.gateway import probe_embedding_dim
from core.ollama.models_info import classify_recommendation, parse_context_window
from core.storage import notebooks_repo

router = APIRouter(prefix="/api", tags=["models"])

_EMBED_NAME_HINTS = ("embed", "bge", "nomic-embed", "mxbai", "snowflake-arctic-embed", "all-minilm")


def _classify_kind(*, capabilities: list[str], name: str) -> str:
    """Task 1 の classify_kind があればそれを使い、無ければローカル判定。"""
    try:
        from core.ollama.models_info import classify_kind  # type: ignore[attr-defined]

        return classify_kind(capabilities=capabilities, name=name)
    except (ImportError, AttributeError):
        caps = {c.lower() for c in capabilities}
        has_embed = "embedding" in caps
        has_chat = "completion" in caps or "chat" in caps
        if has_embed and has_chat:
            return "both"
        if has_embed:
            return "embedding"
        if has_chat:
            return "chat"
        lower = name.lower()
        if any(h in lower for h in _EMBED_NAME_HINTS):
            return "embedding"
        return "chat"


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
        capabilities = show.get("capabilities", []) or []
        kind = _classify_kind(capabilities=capabilities, name=name)
        embedding_dim: int | None = None
        if kind in ("embedding", "both"):
            try:
                embedding_dim = await probe_embedding_dim(ctx.ollama, name)
            except Exception:
                embedding_dim = None
        models.append(
            {
                "name": name,
                "size_bytes": tag.get("size"),
                "context_window": ctx_window,
                "modified_at": tag.get("modified_at"),
                "kind": kind,
                "embedding_dim": embedding_dim,
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

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from core.logging import get_logger
from core.ollama.client import OllamaClient
from core.ollama.gateway import probe_embedding_dim
from core.ollama.models_info import (
    classify_kind,
    classify_recommendation,
    has_vision_capability,
    parse_context_window,
)
from core.storage import notebooks_repo

log = get_logger("api.models")

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
        try:
            show = await client.show(name)
        except Exception:
            # 一部モデルは Ollama 自身の /api/show が 500 を返すことがある
            # (実機確認: gpt-oss 系の一部タグ)。1モデルの show 失敗で
            # モデル一覧全体を巻き込んで 500 にしない — そのモデルだけ
            # 除外して残りを返す(設定画面のモデル選択が全滅するのを防ぐ)。
            log.warning("model_show_failed", model=name, exc_info=True)
            continue
        params_str = show.get("parameters", "")
        ctx_window = parse_context_window(params_str)
        capabilities = show.get("capabilities", []) or []
        kind = classify_kind(capabilities=capabilities, name=name)
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
                "has_vision": has_vision_capability(capabilities),
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

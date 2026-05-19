from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from apps.api.schemas.settings import (
    AppSettingsSchema,
    GenerationSettingsSchema,
    OllamaSettingsSchema,
    RetrievalSettingsSchema,
)

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings", response_model=AppSettingsSchema)
async def get_settings(request: Request) -> AppSettingsSchema:
    cfg = request.app.state.ctx.config
    return AppSettingsSchema(
        ollama=OllamaSettingsSchema(
            endpoint=cfg.ollama.endpoint,
            default_model=cfg.ollama.default_model,
            embedding_model=cfg.ollama.embedding_model,
        ),
        generation=GenerationSettingsSchema(
            context_budget_ratio=cfg.generation.context_budget_ratio,
            response_budget_tokens=cfg.generation.response_budget_tokens,
        ),
        retrieval=RetrievalSettingsSchema(
            top_k=cfg.retrieval.top_k,
            top_k_max=cfg.retrieval.top_k_max,
            min_history_turns=cfg.retrieval.min_history_turns,
        ),
    )


@router.get("/stats")
async def get_stats(request: Request) -> dict[str, Any]:
    ctx = request.app.state.ctx
    nb_count = ctx.conn.execute("SELECT COUNT(*) FROM notebooks").fetchone()[0]
    src_count = ctx.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    chunk_count = ctx.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    return {
        "notebook_count": nb_count,
        "source_count": src_count,
        "chunk_count": chunk_count,
        "data_dir": str(ctx.config.data_dir),
    }

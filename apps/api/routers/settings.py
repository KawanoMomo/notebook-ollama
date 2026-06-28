from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from apps.api.schemas.settings import (
    AppSettingsSchema,
    AudioSettingsSchema,
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
        audio=AudioSettingsSchema(
            mic_device_index=cfg.audio.mic_device_index,
            system_device_index=cfg.audio.system_device_index,
            whisper_model=cfg.audio.whisper_model,
            device=cfg.audio.device,
            compute_type=cfg.audio.compute_type,
            live_caption_default=cfg.audio.live_caption_default,
            agc_enabled=cfg.audio.agc_enabled,
            diarization_enabled=cfg.audio.diarization_enabled,
            max_speakers=cfg.audio.max_speakers,
            voiceprint_naming=cfg.audio.voiceprint_naming,
            name_inference_llm=cfg.audio.name_inference_llm,
            name_threshold=cfg.audio.name_threshold,
            storage_format=cfg.audio.storage_format,
            storage_bitrate_kbps=cfg.audio.storage_bitrate_kbps,
            keep_audio=cfg.audio.keep_audio,
        ),
    )


@router.put("/settings/audio", response_model=AudioSettingsSchema)
async def put_audio_settings(
    request: Request, body: AudioSettingsSchema
) -> AudioSettingsSchema:
    cfg = request.app.state.ctx.config
    # in-memory 反映(編集対象フィールドのみ更新、その他=sample_rate 等は保持)
    cfg.audio = cfg.audio.model_copy(update=body.model_dump())
    # 永続化(編集可能フィールドのみ)
    from core.settings_store import save_section
    save_section(cfg.data_dir, "audio", body.model_dump())
    return body


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

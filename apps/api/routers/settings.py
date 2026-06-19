from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from apps.api.schemas.settings import (
    AppSettingsSchema,
    AudioSettingsSchema,
    GenerationSettingsSchema,
    OllamaSettingsSchema,
    OllamaSettingsUpdate,
    RetrievalSettingsSchema,
)
from core.exceptions import AppError, ErrorCode
from core.ollama.client import OllamaClient
from core.ollama.models_info import classify_kind

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
            auto_title=cfg.audio.auto_title,
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


@router.put("/settings/ollama", response_model=OllamaSettingsSchema)
async def put_ollama_settings(
    request: Request, body: OllamaSettingsUpdate
) -> OllamaSettingsSchema:
    cfg = request.app.state.ctx.config
    client = OllamaClient(
        endpoint=cfg.ollama.endpoint,
        timeout=cfg.ollama.request_timeout_seconds,
    )
    tags = await client.list_tags()
    names = {t.get("name") for t in tags}
    if body.default_model not in names:
        raise AppError(
            ErrorCode.INPUT_INVALID,
            f"model {body.default_model} not found in Ollama",
            remediation="ollama pull で取得済みのモデル名を指定してください。",
        )
    show = await client.show(body.default_model)
    kind = classify_kind(
        capabilities=show.get("capabilities", []) or [],
        name=body.default_model,
    )
    if kind not in ("chat", "both"):
        raise AppError(
            ErrorCode.INPUT_INVALID,
            f"model {body.default_model} is not a chat model (kind={kind})",
            remediation="チャット可能なモデル(chat / both)を選択してください。",
        )

    # in-memory 反映
    cfg.ollama = cfg.ollama.model_copy(update={"default_model": body.default_model})

    # 永続化: ollama セクションをマージ更新する(audio 方式と整合)。
    # default_model のみ更新し、既存の embedding_model / embedding_dim は
    # 「現在の永続値 > in-memory cfg」の優先で保持する。これにより、Task 7 で
    # 768 等へ切替後にユーザが LLM 既定を変えても embedding_dim が 1024 へ
    # 巻き戻らない(決定事項「model と次元は一体」を破壊しない)。
    from core.settings_store import load_overrides, save_section

    existing = load_overrides(cfg.data_dir).get("ollama")
    existing = existing if isinstance(existing, dict) else {}
    embedding_model = existing.get("embedding_model", cfg.ollama.embedding_model)
    # getattr で Task5(OllamaSettings.embedding_dim 追加)の前後どちらでも動く。
    # 既存永続値 > in-memory cfg.embedding_dim(Task5 後) > 既定 1024(Task5 前)。
    embedding_dim = existing.get(
        "embedding_dim", getattr(cfg.ollama, "embedding_dim", 1024)
    )
    save_section(
        cfg.data_dir,
        "ollama",
        {
            "default_model": cfg.ollama.default_model,
            "embedding_model": embedding_model,
            "embedding_dim": embedding_dim,
        },
    )
    return OllamaSettingsSchema(
        endpoint=cfg.ollama.endpoint,
        default_model=cfg.ollama.default_model,
        embedding_model=cfg.ollama.embedding_model,
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

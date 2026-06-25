from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from apps.api.schemas.settings import (
    AppSettingsSchema,
    AudioSettingsSchema,
    EmbeddingSwitchRequest,
    GenerationSettingsSchema,
    OllamaSettingsSchema,
    OllamaSettingsUpdate,
    OllamaTimeoutsUpdate,
    RetrievalSettingsSchema,
)
from core.exceptions import AppError, ErrorCode
from core.ollama.client import OllamaClient
from core.ollama.gateway import probe_embedding_dim
from core.ollama.models_info import classify_kind
from core.settings_store import save_section
from core.storage import chunks_repo, notebooks_repo, sources_repo
from core.storage.vector_store import ChunkVector

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings", response_model=AppSettingsSchema)
async def get_settings(request: Request) -> AppSettingsSchema:
    cfg = request.app.state.ctx.config
    return AppSettingsSchema(
        ollama=OllamaSettingsSchema(
            endpoint=cfg.ollama.endpoint,
            default_model=cfg.ollama.default_model,
            embedding_model=cfg.ollama.embedding_model,
            embedding_dim=request.app.state.ctx.vector_store.collection_dim(),
            request_timeout_seconds=cfg.ollama.request_timeout_seconds,
            chat_read_timeout_seconds=cfg.ollama.chat_read_timeout_seconds,
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
        embedding_dim=request.app.state.ctx.vector_store.collection_dim(),
        request_timeout_seconds=cfg.ollama.request_timeout_seconds,
        chat_read_timeout_seconds=cfg.ollama.chat_read_timeout_seconds,
    )


@router.put("/settings/ollama/timeouts")
async def put_ollama_timeouts(
    request: Request, body: OllamaTimeoutsUpdate
) -> dict[str, float]:
    """Ollama リクエストタイムアウト(秒)を更新する。

    大型モデル(GPT-OSS:20B 等)の初回ロード時に既定値 600 秒では足りない、
    あるいは逆に短くしてフェイルファストしたい場合に UI から変更する経路。

    変更は in-memory cfg と settings.json の両方に反映する。次回起動時は
    settings.json の値が AppConfig の既定を上書きする(env > settings.json > 既定)。
    """
    cfg = request.app.state.ctx.config
    cfg.ollama = cfg.ollama.model_copy(
        update={
            "request_timeout_seconds": body.request_timeout_seconds,
            "chat_read_timeout_seconds": body.chat_read_timeout_seconds,
        }
    )

    # 既存の ollama セクションへ merge 保存(default_model / embedding_* を壊さない)。
    from core.settings_store import load_overrides, save_section
    existing = load_overrides(cfg.data_dir).get("ollama")
    existing = existing if isinstance(existing, dict) else {}
    save_section(
        cfg.data_dir,
        "ollama",
        {
            **existing,
            "request_timeout_seconds": body.request_timeout_seconds,
            "chat_read_timeout_seconds": body.chat_read_timeout_seconds,
        },
    )
    return {
        "request_timeout_seconds": cfg.ollama.request_timeout_seconds,
        "chat_read_timeout_seconds": cfg.ollama.chat_read_timeout_seconds,
    }


_REINDEX_TOPIC = "embedding_reindex"


@router.post("/settings/embedding/switch")
async def switch_embedding(
    request: Request, body: EmbeddingSwitchRequest
) -> dict[str, Any]:
    ctx = request.app.state.ctx
    cfg = ctx.config
    model = body.model

    # 1. model が embedding|both であること検証(list_tags で存在確認 + classify_kind)
    client = OllamaClient(
        endpoint=cfg.ollama.endpoint,
        timeout=cfg.ollama.request_timeout_seconds,
    )
    tags = await client.list_tags()
    names = {t.get("name") for t in tags}
    if model not in names:
        raise AppError(ErrorCode.INPUT_INVALID, f"model {model} not installed")
    show = await client.show(model)
    kind = classify_kind(capabilities=show.get("capabilities", []) or [], name=model)
    if kind not in ("embedding", "both"):
        raise AppError(
            ErrorCode.INPUT_INVALID,
            f"model {model} is not an embedding model (kind={kind})",
        )

    try:
        # 2. 新次元を検出
        new_dim = await probe_embedding_dim(ctx.ollama, model)
        # channel は payload 専用フィールド(SQLite に無い)で recreate 後は失われる。
        # recreate の前に現行 collection から {orig_id: channel} を退避し、
        # 再 upsert 時に carry-forward して録音引用の audio channel を保持する。
        channel_map = ctx.vector_store.export_channels()
        # 3. collection を新次元で再作成(内部 _dim も更新される)
        ctx.vector_store.recreate_collection(new_dim)

        # 4. 全ノートの全チャンクを走査し再埋め込み
        notebooks = notebooks_repo.list_notebooks(ctx.conn)
        all_chunks: list[tuple[str, object]] = []
        for nb in notebooks:
            for src in sources_repo.list_sources(ctx.conn, notebook_id=nb.id):
                for ch in chunks_repo.list_chunks_for_source(ctx.conn, src.id):
                    all_chunks.append((src.kind, ch))
        total = len(all_chunks)

        done = 0
        await ctx.sse.publish(
            _REINDEX_TOPIC,
            {"type": "reindex_progress", "done": done, "total": total},
        )
        for source_kind, ch in all_chunks:
            vector = await ctx.ollama.embed(model=model, text=ch.text)
            ctx.vector_store.upsert(
                [
                    ChunkVector(
                        id=ch.id,
                        vector=vector,
                        notebook_id=ch.notebook_id,
                        source_id=ch.source_id,
                        source_kind=source_kind,
                        page=ch.page,
                        heading_path=ch.heading_path,
                        ord=ch.ord,
                        start_ms=ch.start_ms,
                        end_ms=ch.end_ms,
                        speaker=ch.speaker,
                        channel=channel_map.get(ch.id),
                    )
                ]
            )
            done += 1
            await ctx.sse.publish(
                _REINDEX_TOPIC,
                {"type": "reindex_progress", "done": done, "total": total},
            )

        # 5. in-memory 反映 + settings.json 永続化(default_model は現在値を保持)
        # embedding_dim も併せて更新し、in-memory cfg を coherent に保つ
        # (Critical 修正で embedding_dim が起動時復元に参加するため重要)。
        cfg.ollama = cfg.ollama.model_copy(
            update={"embedding_model": model, "embedding_dim": new_dim}
        )
        save_section(
            cfg.data_dir,
            "ollama",
            {
                "default_model": cfg.ollama.default_model,
                "embedding_model": model,
                "embedding_dim": new_dim,
            },
        )

        # 6. 完了イベント
        await ctx.sse.publish(
            _REINDEX_TOPIC,
            {"type": "reindex_complete", "model": model, "dim": new_dim},
        )
    except AppError:
        raise
    except Exception as exc:
        await ctx.sse.publish(
            _REINDEX_TOPIC,
            {"type": "reindex_error", "message": str(exc)},
        )
        raise AppError(
            ErrorCode.OLLAMA_GENERATION_FAILED,
            "embedding reindex failed",
            detail=str(exc),
        ) from exc

    return {"model": model, "dim": new_dim, "reindexed_chunks": total}


@router.get("/settings/events")
async def settings_events(request: Request) -> EventSourceResponse:
    ctx = request.app.state.ctx
    queue = ctx.sse.subscribe(_REINDEX_TOPIC)

    async def gen() -> AsyncIterator[dict]:
        try:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                    # payload['type'] を SSE event 名へ写像し、data からは type を落とす。
                    event = payload.get("type", "message")
                    data = {k: v for k, v in payload.items() if k != "type"}
                    yield {
                        "event": event,
                        "data": json.dumps(data, ensure_ascii=False),
                    }
                except TimeoutError:
                    yield {"event": "ping", "data": ""}
        finally:
            ctx.sse.unsubscribe(_REINDEX_TOPIC, queue)

    return EventSourceResponse(gen())


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

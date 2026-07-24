from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from apps.api.schemas.settings import (
    AccelerationResponseSchema,
    AppSettingsSchema,
    AudioSettingsSchema,
    BackendPlanSchema,
    CrashReportSettingsSchema,
    CrashReportSettingsUpdate,
    DevSettingsSchema,
    DevSettingsUpdate,
    EmbeddingSwitchRequest,
    GenerationSettingsSchema,
    GenerationSettingsUpdate,
    HwProfileSchema,
    OllamaSettingsSchema,
    OllamaSettingsUpdate,
    OllamaTimeoutsUpdate,
    RetrievalSettingsSchema,
    VisionModelUpdate,
    VoiceInputSettingsSchema,
)
from core.accel.plan import is_phase1_implementable
from core.crash_reporter.settings import CrashReportSettings
from core.exceptions import AppError, ErrorCode
from core.ollama.client import OllamaClient
from core.ollama.gateway import probe_embedding_dim
from core.ollama.models_info import classify_kind, has_vision_capability
from core.settings_store import save_crash_report, save_section
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
            runtime_backend=cfg.ollama.runtime_backend,
            text_embed_backend=cfg.ollama.text_embed_backend,
            request_timeout_seconds=cfg.ollama.request_timeout_seconds,
            chat_read_timeout_seconds=cfg.ollama.chat_read_timeout_seconds,
            vision_model=cfg.ollama.vision_model,
        ),
        generation=GenerationSettingsSchema(
            context_budget_ratio=cfg.generation.context_budget_ratio,
            response_budget_tokens=cfg.generation.response_budget_tokens,
            auto_continue_max=cfg.generation.auto_continue_max,
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
            transcriber_backend=cfg.audio.transcriber_backend,
            diarizer_backend=cfg.audio.diarizer_backend,
            speaker_embed_backend=cfg.audio.speaker_embed_backend,
        ),
        crash_report=CrashReportSettingsSchema(
            enabled=cfg.crash_report.enabled,
            auto_prompt=cfg.crash_report.auto_prompt,
            opted_in_at=cfg.crash_report.opted_in_at,
        ),
        voice_input=VoiceInputSettingsSchema(
            mode=cfg.voice_input.mode,
            ptt_key=cfg.voice_input.ptt_key,
        ),
        dev=DevSettingsSchema(
            enabled=cfg.dev.enabled,
            log_capacity_bytes=cfg.dev.log_capacity_bytes,
        ),
    )


@router.put("/settings/crash-report", response_model=CrashReportSettingsSchema)
async def put_crash_report_settings(
    request: Request, body: CrashReportSettingsUpdate
) -> CrashReportSettingsSchema:
    """クラッシュレポートのオプトイン状態を更新する (S6 / S8 用 PUT)。

    body は部分更新 (``model_dump(exclude_unset=True)``) — UI が変更したい
    フィールドだけ送る前提。残りは現在の in-memory cfg.crash_report を保持する。

    Auto-stamp の契約 (spec §7.3 オプトインフロー):
    - 直前の状態が ``enabled is None`` (= 未決定) で、今回 ``enabled=True`` に
      遷移し、かつ caller が ``opted_in_at`` を明示していないとき、サーバが
      現在時刻 (UTC) を ``opted_in_at`` に自動付与する。これにより UI 側で
      「オプトインを許可しました」のタイムスタンプを別途送らなくても良い。
    - それ以外 (False → True 再オプトインや明示的に opted_in_at を送ったケース)
      ではサーバは何もせず caller の値を尊重する。

    永続化は ``save_crash_report`` 経由で settings.json の crash_report セクション
    だけを書き戻す (audio / ollama セクションは保持される)。
    """
    cfg = request.app.state.ctx.config
    current = cfg.crash_report
    patch = body.model_dump(exclude_unset=True)

    new_enabled = patch.get("enabled", current.enabled)
    new_auto_prompt = patch.get("auto_prompt", current.auto_prompt)
    new_opted_in_at = patch.get("opted_in_at", current.opted_in_at)

    # オプトイン遷移 (None → True) の自動タイムスタンプ。
    # 「opted_in_at が caller から明示的に送られていない」を `model_fields_set`
    # ではなく `'opted_in_at' not in patch` で判定する (exclude_unset 後の dict は
    # 明示送信したフィールドだけを含むので意味的に等価)。
    if (
        current.enabled is None
        and new_enabled is True
        and "opted_in_at" not in patch
    ):
        new_opted_in_at = datetime.now(UTC)

    updated = CrashReportSettings(
        enabled=new_enabled,
        auto_prompt=new_auto_prompt,
        opted_in_at=new_opted_in_at,
    )

    # in-memory 反映 + 永続化 (audio / ollama と同じ規約)。
    cfg.crash_report = updated
    save_crash_report(cfg.data_dir, updated)

    return CrashReportSettingsSchema(
        enabled=updated.enabled,
        auto_prompt=updated.auto_prompt,
        opted_in_at=updated.opted_in_at,
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


@router.put("/settings/voice-input", response_model=VoiceInputSettingsSchema)
async def put_voice_input_settings(
    request: Request, body: VoiceInputSettingsSchema
) -> VoiceInputSettingsSchema:
    """チャット音声入力設定(モード / PTT キー)の更新。audio 方式と同じ規約。"""
    cfg = request.app.state.ctx.config
    cfg.voice_input = cfg.voice_input.model_copy(update=body.model_dump())
    save_section(cfg.data_dir, "voice_input", body.model_dump())
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
    # vision_model(Stage 2)も同じ「既存永続値 > in-memory cfg」の優先で保持する。
    # これを省くと、視覚モデル設定後に既定チャットモデルを変えるたびに
    # settings.json の ollama セクションが 3 キーで丸ごと再構築され、
    # 次回起動時に vision_model が既定値(未設定)へ巻き戻ってしまう。
    vision_model = existing.get(
        "vision_model", getattr(cfg.ollama, "vision_model", "")
    )
    save_section(
        cfg.data_dir,
        "ollama",
        {
            "default_model": cfg.ollama.default_model,
            "embedding_model": embedding_model,
            "embedding_dim": embedding_dim,
            "vision_model": vision_model,
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


@router.put("/settings/vision-model")
async def put_vision_model(request: Request, body: VisionModelUpdate) -> dict:
    """視覚モデル(VLM)スロットの更新(Stage 2)。

    空文字列は「未設定に戻す」として vision capability 検証をスキップする
    (describe段・OCR経路をスキップする合図)。既存の ollama 永続セクションは
    load_overrides で読んだ現行値へ vision_model のみを上書きして保存する
    (put_ollama_timeouts と同じ規約: 他フィールドを巻き戻さない)。
    """
    cfg = request.app.state.ctx.config
    if body.model == "":
        cfg.ollama = cfg.ollama.model_copy(update={"vision_model": ""})
    else:
        client = OllamaClient(
            endpoint=cfg.ollama.endpoint, timeout=cfg.ollama.request_timeout_seconds
        )
        tags = await client.list_tags()
        names = {t.get("name") for t in tags}
        if body.model not in names:
            raise AppError(
                ErrorCode.INPUT_INVALID,
                f"model {body.model} not found in Ollama",
                remediation="ollama pull で取得済みのモデル名を指定してください。",
            )
        show = await client.show(body.model)
        if not has_vision_capability(show.get("capabilities", []) or []):
            raise AppError(
                ErrorCode.INPUT_INVALID,
                f"model {body.model} does not support vision",
                remediation="vision capability を持つモデル(例: qwen3-vl系)を選択してください。",
            )
        cfg.ollama = cfg.ollama.model_copy(update={"vision_model": body.model})

    from core.settings_store import load_overrides, save_section

    existing = load_overrides(cfg.data_dir).get("ollama")
    existing = existing if isinstance(existing, dict) else {}
    save_section(
        cfg.data_dir,
        "ollama",
        {**existing, "vision_model": cfg.ollama.vision_model},
    )
    return {"vision_model": cfg.ollama.vision_model}


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


@router.put("/settings/generation", response_model=GenerationSettingsSchema)
async def put_generation_settings(
    request: Request, body: GenerationSettingsUpdate
) -> GenerationSettingsSchema:
    """生成設定(応答トークン上限 等)を更新する。

    response_budget_tokens は num_predict にそのまま渡る。思考モデルの
    thinking もこの予算を消費するため、長出力が「上限打ち切り」になる場合に
    UI から拡大する経路(2026-07-05 実機FB: 表示だけあって変更できなかった)。
    変更は in-memory cfg と settings.json の両方に反映し、次回起動時は
    settings.json の値が既定を上書きする(env > settings.json > 既定)。
    """
    cfg = request.app.state.ctx.config
    update: dict = {"response_budget_tokens": body.response_budget_tokens}
    if body.context_budget_ratio is not None:
        update["context_budget_ratio"] = body.context_budget_ratio
    if body.auto_continue_max is not None:
        update["auto_continue_max"] = body.auto_continue_max
    cfg.generation = cfg.generation.model_copy(update=update)

    from core.settings_store import load_overrides, save_section
    existing = load_overrides(cfg.data_dir).get("generation")
    existing = existing if isinstance(existing, dict) else {}
    save_section(
        cfg.data_dir,
        "generation",
        {
            **existing,
            "response_budget_tokens": cfg.generation.response_budget_tokens,
            "context_budget_ratio": cfg.generation.context_budget_ratio,
            "auto_continue_max": cfg.generation.auto_continue_max,
        },
    )
    return GenerationSettingsSchema(
        context_budget_ratio=cfg.generation.context_budget_ratio,
        response_budget_tokens=cfg.generation.response_budget_tokens,
        auto_continue_max=cfg.generation.auto_continue_max,
    )


@router.put("/settings/dev", response_model=DevSettingsSchema)
async def put_dev_settings(
    request: Request, body: DevSettingsUpdate
) -> DevSettingsSchema:
    """開発者モードの ON/OFF と保持容量を更新する(spec §9.2 / §11 S2, S5)。

    - 容量は 1MB..200MB にクランプして採用し、採用値を返す(範囲外でも 400 にしない)
    - ON 遷移: DevLogRing.enable(容量) — 収集はこの瞬間から始まる(FR-6)
    - OFF 遷移: ring.disable → broker へ shutdown 配信(購読側は自動クローズ)
    - ON のまま容量変更: ring.resize(縮小時は古い側から即時 drop)
    """
    from core.dev_logs.broker import broker as dev_broker
    from core.dev_logs.ring import clamp_capacity
    from core.dev_logs.ring import ring as dev_ring

    cfg = request.app.state.ctx.config
    was_enabled = cfg.dev.enabled
    capacity = clamp_capacity(
        body.log_capacity_bytes
        if body.log_capacity_bytes is not None
        else cfg.dev.log_capacity_bytes
    )
    cfg.dev = cfg.dev.model_copy(
        update={"enabled": body.enabled, "log_capacity_bytes": capacity}
    )

    if body.enabled and not was_enabled:
        dev_ring.enable(capacity_bytes=capacity)
    elif not body.enabled and was_enabled:
        dev_ring.disable()
        dev_broker.shutdown_all()
    elif body.enabled:
        dev_ring.resize(capacity_bytes=capacity)

    from core.settings_store import save_section
    save_section(
        cfg.data_dir,
        "dev",
        {"enabled": cfg.dev.enabled, "log_capacity_bytes": cfg.dev.log_capacity_bytes},
    )
    return DevSettingsSchema(
        enabled=cfg.dev.enabled, log_capacity_bytes=cfg.dev.log_capacity_bytes
    )


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


@router.get("/settings/acceleration", response_model=AccelerationResponseSchema)
async def get_acceleration(request: Request) -> AccelerationResponseSchema:
    """Read-only view of the resolved hardware probe + backend plan.

    Sprint 3 / Task 3.5. The response is a serialization of
    ``ctx.hw_profile`` + ``ctx.backend_plan`` (set once during ``build_context``)
    plus the Phase 1 implementability gate. No probe / planner work runs
    per-request — re-probing requires a process restart in Phase 1.

    Phase 1 is **read-only**: there is intentionally no companion
    ``PUT /api/settings/acceleration`` and the AccelerationPanel.svelte tab
    has no override <select> / [Apply] button. Per-role backend selection
    via UI lands in Phase 2.
    """
    ctx = request.app.state.ctx
    hw = ctx.hw_profile
    plan = ctx.backend_plan
    return AccelerationResponseSchema(
        hw_profile=HwProfileSchema(
            cpu_brand=hw.cpu_brand,
            # Field rename: ``has_cuda`` -> ``cuda`` for the public API.
            # The dataclass keeps the ``has_`` prefix so probe-internal code
            # reads naturally; the UI talks about "CUDA available".
            cuda=hw.has_cuda,
            dgpu=hw.dgpu,
            igpu=hw.igpu,
            npu=hw.npu,
            vram_mb=hw.vram_mb,
            ryzen_ai_gen=hw.ryzen_ai_gen,
            # tuple -> list for JSON-native serialization.
            openvino_devices=list(hw.openvino_devices),
            has_directml=hw.has_directml,
        ),
        backend_plan=BackendPlanSchema(
            stt_id=plan.stt_id,
            diarize_id=plan.diarize_id,
            llm_id=plan.llm_id,
            text_embed_id=plan.text_embed_id,
            reason=plan.reason,
        ),
        is_phase1_implementable=is_phase1_implementable(plan),
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

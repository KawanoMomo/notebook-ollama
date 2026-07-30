from __future__ import annotations

import asyncio
import logging
import sqlite3
from typing import TYPE_CHECKING, Any

from apps.api.sse import SseBroker
from core.accel.factory import BackendFactory
from core.accel.plan import BackendPlan, is_phase1_implementable
from core.accel.planner import BackendPlanner
from core.accel.probe import HardwareProbe
from core.accel.profile import HwProfile
from core.adr.adr_job import AdrDeps, AdrJob
from core.config import AppConfig
from core.feature_service import FeatureService
from core.generation.stream import GenerationDeps, GenerationService
from core.ingestion.figure_describer import LazyFigureDescriber
from core.ingestion.ocr_engine import LazyOcrEngine
from core.ingestion.pipeline import IngestionPipeline, PipelineDeps
from core.logging import get_logger
from core.ollama.client import OllamaClient
from core.ollama.gateway import OllamaGateway, probe_vision_capability
from core.recording.session import RecordingRegistry
from core.retrieval.search import RetrievalService
from core.settings_store import load_overrides
from core.storage.assets_repo import list_assets_for_chunk_ids, list_assets_for_desc_chunk_ids
from core.storage.database import connect, migrate
from core.storage.vector_store import VectorStore
from core.summary.registry import SummaryTaskRegistry
from core.summary.summarizer import SummaryDeps, SummaryJob

# 録音スタック(faster-whisper / sherpa-onnx / soundfile / scipy …)は
# `[project.optional-dependencies] recording` の opt-in extra。ベース install
# (=`uv sync` 単体)では soundfile が無く、`core.recording.recording_pipeline`
# のトップレベル import が ModuleNotFoundError でこける。これを起動時に巻き込むと
# uvicorn が app import の段階で死に、録音機能を使う気がないユーザーまでアプリが
# 起動しない。README が `recording` extra を opt-in と明言している以上、依存欠落
# は「録音エンドポイントだけが 503」になる形で degrade させ、起動はさせる。
if TYPE_CHECKING:  # pragma: no cover - typing only
    from core.accel.factory import _TextEmbedderLike
    from core.recording.recording_pipeline import RecordingPipeline

logger = logging.getLogger(__name__)

_DEFAULT_EMBEDDING_DIM = 1024  # bge-m3

_log = get_logger("apps.api.dependencies")


def _resolve_embedding_dim(config: AppConfig) -> int:
    """起動時の VectorStore 次元を決める(Ollama は叩かない)。

    1. 既存 collection があればその次元を採用(問い合わせ用 store を開いて閉じる)。
    2. 無ければ settings.json の ollama.embedding_dim を採用。
    3. それも無ければ既定 1024。
    """
    probe_store = VectorStore(path=config.qdrant_path, dim=_DEFAULT_EMBEDDING_DIM)
    try:
        existing = probe_store.collection_dim()
    finally:
        probe_store.close()
    if existing is not None:
        return existing
    ov = load_overrides(config.data_dir)
    ollama_ov = ov.get("ollama")
    if isinstance(ollama_ov, dict):
        dim = ollama_ov.get("embedding_dim")
        if isinstance(dim, int) and dim > 0:
            return dim
    return _DEFAULT_EMBEDDING_DIM


def _degrade_to_cpu_plan(
    planner: BackendPlanner, original_hw: HwProfile
) -> BackendPlan:
    """Re-run the planner against a stripped-down CPU-only ``HwProfile``.

    Used as the safety policy when ``is_phase1_implementable`` returns False:
    the Planner picked an id that the Phase 1 Factory cannot yet build (e.g.
    ``openvino-whisper-igpu`` on an Intel Meteor Lake box). Rather than crash
    startup, we synthesize a CPU-only profile that preserves the host's
    ``cpu_brand`` and re-plan — the result is guaranteed to be Phase 1
    implementable (``faster-whisper-cpu`` + ``sherpa-onnx-cpu`` +
    ``ollama-cuda`` + ``ollama-bge-m3-cpu`` — Ollama auto-degrades to CPU on
    GPU-less hosts).
    """
    cpu_hw = HwProfile(
        vendor="unknown",
        cpu_brand=original_hw.cpu_brand,
        dgpu=None,
        igpu=None,
        npu=None,
        vram_mb=None,
        ryzen_ai_gen=None,
        openvino_devices=(),
        has_directml=False,
        has_cuda=False,
        cuda_device_count=0,
    )
    return planner.plan(cpu_hw)


class AppContext:
    """Shared application state assembled by :func:`build_context`.

    Implemented as a plain class (not a dataclass) so that ``transcriber`` /
    ``diarizer`` can be exposed as lazy ``@property`` accessors — building the
    real ``Transcriber`` loads faster-whisper / WhisperModel (gigabytes of
    weights), so we defer that work until the first recording request rather
    than paying it at process startup.

    The lazy attributes still go through ``ctx.backend_factory.build_*`` —
    the Factory wraps the existing concrete classes with identical
    constructor args, so on the dev box (RTX 2080 Ti, plan stt_id=
    ``faster-whisper-cuda``) the resulting object is bit-equivalent to the
    pre-DI lazy ``Transcriber(...)`` construction in ``recordings.py``.

    ``recording_pipeline`` is ``None`` when the `recording` extra is not
    installed (soundfile / scipy / faster-whisper 等が欠落) — 録音系ルータは
    ``_require_recording_pipeline`` でこれを見て 503 を返す。

    Test hooks honoured by ``apps.api.routers.recordings``:

    * ``ctx.transcriber_factory`` — legacy 0-arg callable that returns a
      fake transcriber. When set, the recordings router uses it INSTEAD of
      the lazy ``ctx.transcriber`` property (existing test suite relies on
      this; see ``tests/integration/test_api/test_recordings_api.py``).
    * ``ctx.diarizer_factory`` — same shape for the diarizer.
    """

    def __init__(
        self,
        *,
        config: AppConfig,
        conn: sqlite3.Connection,
        vector_store: VectorStore,
        ollama: OllamaGateway,
        sse: SseBroker,
        pipeline: IngestionPipeline,
        retrieval: RetrievalService,
        generation: GenerationService,
        recordings: RecordingRegistry,
        recording_pipeline: RecordingPipeline | None,
        summary_runner: Any,
        summary_tasks: SummaryTaskRegistry,
        adr_runner: Any,
        hw_profile: HwProfile,
        backend_plan: BackendPlan,
        backend_factory: BackendFactory,
        ollama_gateway: OllamaGateway,
        text_embedder: _TextEmbedderLike,
        visual_store: Any = None,
        visual_stores: Any = None,
        visual_encoder: Any = None,
    ) -> None:
        self.config = config
        self.conn = conn
        self.vector_store = vector_store
        # ``ctx.ollama`` is the legacy attribute name still used by ingestion /
        # retrieval / generation / recording_pipeline. ``ctx.ollama_gateway``
        # is the Sprint 3 DI name documented in the implementation plan;
        # both point at the same instance to avoid a second HTTP client.
        self.ollama = ollama
        self.ollama_gateway = ollama_gateway
        self.sse = sse
        self.pipeline = pipeline
        self.retrieval = retrieval
        self.generation = generation
        self.recordings = recordings
        self.recording_pipeline = recording_pipeline
        self.summary_runner = summary_runner
        self.summary_tasks = summary_tasks
        self.adr_runner = adr_runner
        # Sprint 3 DI fields ------------------------------------------------
        self.hw_profile = hw_profile
        self.backend_plan = backend_plan
        self.backend_factory = backend_factory
        self.text_embedder = text_embedder
        self.visual_store = visual_store
        self.visual_stores = visual_stores or {}
        self.visual_encoder = visual_encoder
        # Lazy backend instances (built on first access via @property).
        self._transcriber: Any = None
        self._diarizer_resolved: bool = False
        self._diarizer: Any = None

    # ------------------------------------------------------------------
    # Lazy backend properties
    # ------------------------------------------------------------------

    @property
    def transcriber(self) -> Any:
        """Lazily build the STT transcriber via :class:`BackendFactory`.

        Cached after the first access so the WhisperModel load cost is paid
        at most once. Tests can pre-seed by assigning ``ctx.transcriber =
        fake_tr``; the assignment goes through the setter which stores into
        the same private slot the getter reads from.
        """
        if self._transcriber is None:
            self._transcriber = self.backend_factory.build_transcriber(
                self.backend_plan, self.config.audio
            )
        return self._transcriber

    @transcriber.setter
    def transcriber(self, value: Any) -> None:
        self._transcriber = value

    @property
    def diarizer(self) -> Any:
        """Lazily build the speaker diarizer via :class:`BackendFactory`.

        Returns ``None`` when diarization is disabled OR the ONNX model
        files are not present on disk — matches the pre-DI behaviour in
        ``recordings.py::_get_diarizer`` so the offline pipeline degrades
        gracefully to single-speaker mode when models haven't been
        downloaded yet.

        The factory itself only stringifies the paths; the existence check
        and "models not on disk -> degrade to None" decision lives here so
        the Factory stays pure (data in, object out, no I/O probing).
        """
        if self._diarizer_resolved:
            return self._diarizer
        self._diarizer_resolved = True
        cfg = self.config.audio
        if not cfg.diarization_enabled:
            self._diarizer = None
            return None
        from pathlib import Path

        seg = cfg.diarizer_segmentation_model or str(
            self.config.data_dir
            / "models"
            / "sherpa-onnx-pyannote-segmentation-3-0"
            / "model.onnx"
        )
        emb = cfg.diarizer_embedding_model or str(
            self.config.data_dir
            / "models"
            / "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
        )
        if not (Path(seg).exists() and Path(emb).exists()):
            self._diarizer = None
            return None
        try:
            # AudioSettings is a pydantic model; ``model_copy(update=...)``
            # returns a new instance with resolved paths so the Factory's
            # "paths must be non-empty" guard passes.
            resolved_cfg = cfg.model_copy(
                update={
                    "diarizer_segmentation_model": seg,
                    "diarizer_embedding_model": emb,
                }
            )
            self._diarizer = self.backend_factory.build_diarizer(
                self.backend_plan, resolved_cfg
            )
        except Exception:
            # Mirrors the pre-DI graceful-degradation behaviour: if the
            # diarizer fails to construct (e.g. corrupt model, sherpa_onnx
            # missing), surface as None rather than crashing the pipeline.
            self._diarizer = None
        return self._diarizer

    @diarizer.setter
    def diarizer(self, value: Any) -> None:
        self._diarizer_resolved = True
        self._diarizer = value


def build_context(config: AppConfig) -> AppContext:
    config.ensure_dirs()
    conn = connect(config.metadata_db_path)
    migrate(conn)
    resolved_dim = _resolve_embedding_dim(config)
    vs = VectorStore(path=config.qdrant_path, dim=resolved_dim)
    vs.ensure_collection()

    # ------------------------------------------------------------------
    # Sprint 3 / Task 3.4 — accel probe + plan + factory wiring.
    # ------------------------------------------------------------------
    # Probe ordering: hardware first (cheap on dev box, short-circuited to
    # _STUB_PROFILE when NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE=1), then planner
    # picks the per-role backend ids, then the implementability gate
    # ensures the Phase 1 Factory can actually build them. A plan that
    # passes the gate is bit-identical to the pre-Sprint-3 wiring on the
    # RTX 2080 Ti dev box (faster-whisper-cuda / sherpa-onnx-cpu /
    # ollama-cuda / ollama-bge-m3-cpu) — end users see identical behaviour.
    hw_profile = HardwareProbe().run()
    planner = BackendPlanner()
    backend_plan = planner.plan(hw_profile)
    if not is_phase1_implementable(backend_plan):
        # Phase 1 only ships CUDA + CPU builders. When the Planner picks a
        # Phase 2 id (e.g. ``openvino-whisper-igpu`` on an Intel Meteor Lake
        # box) the plan is *valid* but not yet *buildable*. Per the plan's
        # safety policy we warn and degrade to a CPU-only plan rather than
        # crash startup — the user can still record / chat, just without
        # the iGPU/NPU acceleration that Phase 2 will bring.
        _log.warning(
            "backend_plan_not_phase1_implementable",
            stt_id=backend_plan.stt_id,
            diarize_id=backend_plan.diarize_id,
            llm_id=backend_plan.llm_id,
            text_embed_id=backend_plan.text_embed_id,
            reason=backend_plan.reason,
            action="degrade_to_cpu_plan",
        )
        backend_plan = _degrade_to_cpu_plan(planner, hw_profile)
    backend_factory = BackendFactory()

    # Build the LLM gateway through the Factory so the construction path is
    # spec-compliant; this replaces the previous direct ``OllamaClient`` +
    # ``OllamaGateway`` construction in ``build_context``. The Factory's
    # ``_build_ollama_gateway`` uses identical ``endpoint`` / timeouts /
    # ``embedding_options`` wiring, so behaviour is preserved.
    gateway = backend_factory.build_llm_gateway(backend_plan, config.ollama)

    # Text embedder is the Phase 1 ``_OllamaTextEmbedder`` wrapper bound to
    # ``config.ollama.embedding_model``. Existing call sites still use
    # ``ctx.ollama.embed(model=embedding_model, text=...)`` directly so the
    # wrapper is additive — Phase 2 OpenVINO embedders will implement the
    # same protocol and let consumers switch via ``ctx.text_embedder``.
    #
    # Pass the LLM-side ``gateway`` through so the Factory reuses it rather
    # than opening a second ``OllamaGateway`` (and a second httpx client).
    # Runtime invariant: exactly ONE ``OllamaGateway`` per process.
    text_embedder = backend_factory.build_text_embedder(
        backend_plan, config.ollama, gateway=gateway
    )

    sse_broker = SseBroker()

    summary_job = SummaryJob(
        deps=SummaryDeps(
            conn=conn,
            llm=gateway,
            model=config.ollama.default_model,
            # 設定変更(PUT /api/settings/ollama)は cfg.ollama を差し替えるため、
            # 起動時の文字列キャプチャでは切替が反映されない。getter で実行時解決する。
            model_getter=lambda: config.ollama.default_model,
            broker=sse_broker,
        )
    )

    summary_tasks = SummaryTaskRegistry()

    async def _summary_runner(source_id: str) -> None:
        # Best-effort: 失敗しても呼び出し元(取込パイプライン or summarize endpoint)を
        # 巻き込まない。SummaryJob 内部で status を error に落とす。
        # 内側を別タスク化して registry に登録し、/summarize/cancel から
        # キャンセル可能にする(取込・録音経由の自動要約も対象)。
        task = asyncio.create_task(summary_job.run(source_id=source_id))
        summary_tasks.register(source_id, task)
        try:
            await task
        except asyncio.CancelledError:
            # ユーザー中断(registry.cancel)。status の復帰は cancel エンドポイント
            # 側で行う。呼び出し元パイプラインへは伝播させない。
            if not task.cancelled():
                raise
        except Exception:  # noqa: S110 — SummaryJob logs + persists its own error status
            pass
        finally:
            summary_tasks.unregister(source_id, task)

    adr_job = AdrJob(
        deps=AdrDeps(
            conn=conn,
            llm=gateway,
            model=config.ollama.default_model,
            model_getter=lambda: config.ollama.default_model,
            broker=sse_broker,
        )
    )

    async def _adr_runner(source_id: str) -> None:
        # Best-effort: 失敗しても呼び出し元(adr endpoint)を巻き込まない。
        # AdrJob 内部で adr_status を error / skipped に落とす。
        try:
            await adr_job.run(source_id=source_id)
        except Exception:  # noqa: S110 — AdrJob logs + persists its own error / skipped status
            pass

    # ctx.features は build_context() の戻り値に main.py の lifespan で後付けされる
    # (循環依存: AppContext がまだ存在しないためここでは参照できない)。FeatureService は
    # settings.json を毎回読み直すだけの stateless なクラスなので、ここでもう一つ
    # 独立インスタンスを作って参照しても、常に同じ設定を読むため問題ない。
    _pipeline_features = FeatureService(config.data_dir)
    pipeline = IngestionPipeline(
        deps=PipelineDeps(
            conn=conn,
            vector_store=vs,
            ollama=gateway,
            embedding_model=config.ollama.embedding_model,
            embedding_model_getter=lambda: config.ollama.embedding_model,
            broker=sse_broker,
            summary_runner=_summary_runner,
            assets_dir=config.assets_dir,
            assets_enabled=lambda: _pipeline_features.is_enabled("table-figure-rag"),
            figure_describer=LazyFigureDescriber(
                client=gateway,
                model_getter=lambda: config.ollama.vision_model,
                enabled_getter=lambda: _pipeline_features.is_enabled("table-figure-rag"),
            ),
            figure_describe_enabled=lambda: (
                config.ollama.auto_describe_figures
                and bool(config.ollama.vision_model)
                and _pipeline_features.is_enabled("table-figure-rag")
            ),
            ocr_engine=LazyOcrEngine(
                client=gateway,
                model_getter=lambda: config.ollama.vision_model,
                enabled_getter=lambda: _pipeline_features.is_enabled("table-figure-rag"),
            ),
        )
    )
    from core.storage.visual_store import VisualUnitStore
    from core.visual.encoder import TransformersVisualEncoder, visual_extra_available

    # 単位ごとに別コレクション。QdrantClient は VectorStore と共有する
    # (ローカルモードは1パス1クライアント制約)。
    visual_stores = {
        "page": VisualUnitStore(client=vs.client, unit="page"),
        "tile": VisualUnitStore(client=vs.client, unit="tile"),
    }
    visual_store = visual_stores["page"]   # 既存呼び出し(sources.py)との互換
    visual_encoder = (
        TransformersVisualEncoder(
            model_name=config.visual.embedding_model,
            idle_unload_seconds=config.visual.idle_unload_seconds,
            cpu_threads=config.visual.cpu_threads,
            prefer_performance_cores=config.visual.cpu_prefer_performance_cores,
        )
        if visual_extra_available()
        else None
    )

    from core.retrieval.search import VisualSearchDeps
    from core.storage.visual_index_repo import get_meta as _visual_get_meta

    retrieval = RetrievalService(
        conn=conn,
        vector_store=vs,
        ollama=gateway,
        embedding_model=config.ollama.embedding_model,
        embedding_model_getter=lambda: config.ollama.embedding_model,
        figure_desc_enabled=lambda: _pipeline_features.is_enabled("table-figure-rag"),
        visual=VisualSearchDeps(
            stores=visual_stores,
            encoder=visual_encoder,
            enabled=lambda: (
                config.visual.search_enabled
                and visual_encoder is not None
                and _pipeline_features.is_enabled("table-figure-rag")
            ),
            meta_lookup=lambda nb_id, unit: _visual_get_meta(conn, nb_id, unit),
            model_name_getter=lambda: config.visual.embedding_model,
            unit_getter=lambda: config.visual.index_unit,
            strategy_getter=lambda: config.visual.search_strategy,
            tile_grid_getter=lambda: (config.visual.tile_rows, config.visual.tile_cols),
            max_images_getter=lambda: config.visual.max_images,
        ),
    )

    async def _probe_vision(model: str) -> bool:
        # 判定対象は「実際に応答生成へ使われるモデル」。呼び出し元(chat.py)が
        # nb.default_model or ctx.config.ollama.default_model で解決済みの値を
        # 渡してくる — ここでグローバル既定(config.ollama.default_model)を
        # 見ると、ノートブック単位で vision 対応モデルに上書きしているのに
        # 誤って非vision判定される(実機検証で確認)。
        # 取込時の図説明/OCR専用モデル(vision_model)とは別軸(spec §7)。
        if not _pipeline_features.is_enabled("table-figure-rag"):
            return False
        # pixel_native はチャットモデルの vision 能力だけが要件。Stage 2 の
        # vision_model(取込時OCR用)を設定していないユーザーでも使えるように、
        # この戦略のときだけ vision_model の有無を条件から外す。
        if config.visual.search_strategy != "pixel_native" and not config.ollama.vision_model:
            return False
        client = OllamaClient(
            endpoint=config.ollama.endpoint, timeout=config.ollama.request_timeout_seconds
        )
        return await probe_vision_capability(client, model)

    def _lookup_figure_images(chunk_ids: list[str]) -> dict[str, bytes]:
        assets_by_desc_chunk = list_assets_for_desc_chunk_ids(conn, chunk_ids)
        out: dict[str, bytes] = {}
        for cid, asset in assets_by_desc_chunk.items():
            if not asset.image_path:
                continue
            path = config.assets_dir / asset.image_path
            if path.exists():
                out[cid] = path.read_bytes()
        return out

    def _visual_image_path(sid: str, page: int, tile_index: int | None):
        """視覚ヒットの画像ファイル。単位ごとに保存先が違う(VisualIndexBuilder)。"""
        if tile_index is None:
            return config.assets_dir / sid / "pages" / f"{page}.png"
        return config.assets_dir / sid / "tiles" / f"{page}-{tile_index}.png"

    def _lookup_page_images(
        keys: list[tuple[str, int, int | None]],
    ) -> dict[tuple[str, int, int | None], bytes]:
        out: dict[tuple[str, int, int | None], bytes] = {}
        for key in keys:
            sid, page, tile_index = key
            path = _visual_image_path(sid, page, tile_index)
            if path.exists():
                out[key] = path.read_bytes()
            else:
                # 索引未構築 / 別単位で構築済み などで欠落しうる。無言で
                # 落とすと「本文も画像も無いソース」の原因が追えないので残す。
                _log.warning("visual_image_missing", source_id=sid, page=page, tile=tile_index)
        return out

    generation = GenerationService(
        deps=GenerationDeps(
            retrieval=retrieval,
            ollama=gateway,
            assets_lookup=lambda chunk_ids: (
                list_assets_for_chunk_ids(conn, chunk_ids)
                if _pipeline_features.is_enabled("table-figure-rag")
                else {}
            ),
            vision_check=_probe_vision,
            figure_images_lookup=_lookup_figure_images,
            page_images_lookup=_lookup_page_images,
            visual_strategy=lambda: config.visual.search_strategy,
            max_images_getter=lambda: config.visual.max_images,
        )
    )
    recordings = RecordingRegistry()
    # `recording` extra (faster-whisper / sherpa-onnx / soundfile …)が未導入の
    # ベース install では recording_pipeline.py の top-level import が
    # ModuleNotFoundError でこける。ここで握ってログを出し、recording_pipeline=None
    # にしておけば残りのアプリ(ingest / chat / MCP / crash-report …)は起動する。
    # 録音系ルータ側は None を見たら 503("recording extras not installed")を返す。
    try:
        from core.recording.recording_pipeline import RecordingPipeline, RecordingPipelineDeps
        recording_pipeline: RecordingPipeline | None = RecordingPipeline(
            deps=RecordingPipelineDeps(
                conn=conn,
                vector_store=vs,
                ollama=gateway,
                embedding_model=config.ollama.embedding_model,
                embedding_model_getter=lambda: config.ollama.embedding_model,
                broker=sse_broker,
                summary_runner=_summary_runner,
            )
        )
    except ModuleNotFoundError as exc:
        logger.warning(
            "recording extras not installed (%s); recording endpoints will return 503. "
            "Run `uv sync --extra recording` to enable.",
            exc.name or exc,
        )
        recording_pipeline = None
    return AppContext(
        config=config,
        conn=conn,
        vector_store=vs,
        ollama=gateway,
        sse=sse_broker,
        pipeline=pipeline,
        retrieval=retrieval,
        generation=generation,
        recordings=recordings,
        recording_pipeline=recording_pipeline,
        summary_runner=_summary_runner,
        summary_tasks=summary_tasks,
        adr_runner=_adr_runner,
        hw_profile=hw_profile,
        backend_plan=backend_plan,
        backend_factory=backend_factory,
        ollama_gateway=gateway,
        text_embedder=text_embedder,
        visual_store=visual_store,
        visual_stores=visual_stores,
        visual_encoder=visual_encoder,
    )

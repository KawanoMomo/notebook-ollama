from __future__ import annotations

import contextlib
import logging
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from apps.api.sse import SseBroker
from core.adr.adr_job import AdrDeps, AdrJob
from core.config import AppConfig
from core.generation.stream import GenerationDeps, GenerationService
from core.ingestion.pipeline import IngestionPipeline, PipelineDeps
from core.ollama.client import OllamaClient
from core.ollama.gateway import OllamaGateway
from core.recording.session import RecordingRegistry
from core.retrieval.search import RetrievalService
from core.settings_store import load_overrides
from core.storage.database import connect, migrate
from core.storage.vector_store import VectorStore
from core.summary.summarizer import SummaryDeps, SummaryJob

# 録音スタック(faster-whisper / sherpa-onnx / soundfile / scipy …)は
# `[project.optional-dependencies] recording` の opt-in extra。ベース install
# (=`uv sync` 単体)では soundfile が無く、`core.recording.recording_pipeline`
# のトップレベル import が ModuleNotFoundError でこける。これを起動時に巻き込むと
# uvicorn が app import の段階で死に、録音機能を使う気がないユーザーまでアプリが
# 起動しない。README が `recording` extra を opt-in と明言している以上、依存欠落
# は「録音エンドポイントだけが 503」になる形で degrade させ、起動はさせる。
if TYPE_CHECKING:  # pragma: no cover - typing only
    from core.recording.recording_pipeline import RecordingPipeline

logger = logging.getLogger(__name__)

_DEFAULT_EMBEDDING_DIM = 1024  # bge-m3


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


@dataclass
class AppContext:
    config: AppConfig
    conn: sqlite3.Connection
    vector_store: VectorStore
    ollama: OllamaGateway
    sse: SseBroker
    pipeline: IngestionPipeline
    retrieval: RetrievalService
    generation: GenerationService
    recordings: RecordingRegistry
    # None when the `recording` extra is not installed (soundfile / scipy /
    # faster-whisper 等が欠落)。録音系ルータはこの場合 503 を返す。
    # `from __future__ import annotations` のため、TYPE_CHECKING 経由の参照でも
    # 文字列扱いになり runtime import は発生しない(クォート不要)。
    recording_pipeline: RecordingPipeline | None
    summary_runner: object  # async callable: (source_id: str) -> awaitable
    adr_runner: object  # async callable: (source_id: str) -> awaitable


def build_context(config: AppConfig) -> AppContext:
    config.ensure_dirs()
    conn = connect(config.metadata_db_path)
    migrate(conn)
    resolved_dim = _resolve_embedding_dim(config)
    vs = VectorStore(path=config.qdrant_path, dim=resolved_dim)
    vs.ensure_collection()
    raw_client = OllamaClient(
        endpoint=config.ollama.endpoint,
        timeout=config.ollama.request_timeout_seconds,
        chat_read_timeout=config.ollama.chat_read_timeout_seconds,
    )
    gateway = OllamaGateway(
        client=raw_client,
        embedding_options=config.ollama.embedding_options or None,
    )
    sse_broker = SseBroker()

    summary_job = SummaryJob(
        deps=SummaryDeps(
            conn=conn,
            llm=gateway,
            model=config.ollama.default_model,
            broker=sse_broker,
        )
    )

    async def _summary_runner(source_id: str) -> None:
        # Best-effort: 失敗しても呼び出し元(取込パイプライン or summarize endpoint)を
        # 巻き込まない。SummaryJob 内部で status を error に落とす。
        with contextlib.suppress(Exception):
            await summary_job.run(source_id=source_id)

    adr_job = AdrJob(
        deps=AdrDeps(
            conn=conn,
            llm=gateway,
            model=config.ollama.default_model,
            broker=sse_broker,
        )
    )

    async def _adr_runner(source_id: str) -> None:
        # Best-effort: 失敗しても呼び出し元(adr endpoint)を巻き込まない。
        # AdrJob 内部で adr_status を error / skipped に落とす。
        with contextlib.suppress(Exception):
            await adr_job.run(source_id=source_id)

    pipeline = IngestionPipeline(
        deps=PipelineDeps(
            conn=conn,
            vector_store=vs,
            ollama=gateway,
            embedding_model=config.ollama.embedding_model,
            embedding_model_getter=lambda: config.ollama.embedding_model,
            broker=sse_broker,
            summary_runner=_summary_runner,
        )
    )
    retrieval = RetrievalService(
        conn=conn,
        vector_store=vs,
        ollama=gateway,
        embedding_model=config.ollama.embedding_model,
        embedding_model_getter=lambda: config.ollama.embedding_model,
    )
    generation = GenerationService(deps=GenerationDeps(retrieval=retrieval, ollama=gateway))
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
        adr_runner=_adr_runner,
    )

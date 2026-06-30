from __future__ import annotations

import contextlib
import sqlite3
from dataclasses import dataclass

from apps.api.sse import SseBroker
from core.adr.adr_job import AdrDeps, AdrJob
from core.config import AppConfig
from core.generation.stream import GenerationDeps, GenerationService
from core.ingestion.pipeline import IngestionPipeline, PipelineDeps
from core.ollama.client import OllamaClient
from core.ollama.gateway import OllamaGateway
from core.recording.recording_pipeline import RecordingPipeline, RecordingPipelineDeps
from core.recording.session import RecordingRegistry
from core.retrieval.search import RetrievalService
from core.settings_store import load_overrides
from core.storage.database import connect, migrate
from core.storage.vector_store import VectorStore
from core.summary.summarizer import SummaryDeps, SummaryJob

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
    recording_pipeline: RecordingPipeline
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
    recording_pipeline = RecordingPipeline(
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

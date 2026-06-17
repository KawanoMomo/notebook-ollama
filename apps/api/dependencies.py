from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from apps.api.sse import SseBroker
from core.config import AppConfig
from core.generation.stream import GenerationDeps, GenerationService
from core.ingestion.pipeline import IngestionPipeline, PipelineDeps
from core.ollama.client import OllamaClient
from core.ollama.gateway import OllamaGateway
from core.recording.session import RecordingRegistry
from core.retrieval.search import RetrievalService
from core.storage.database import connect, migrate
from core.storage.vector_store import VectorStore

_EMBEDDING_DIM = 1024  # bge-m3


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


def build_context(config: AppConfig) -> AppContext:
    config.ensure_dirs()
    conn = connect(config.metadata_db_path)
    migrate(conn)
    vs = VectorStore(path=config.qdrant_path, dim=_EMBEDDING_DIM)
    vs.ensure_collection()
    raw_client = OllamaClient(
        endpoint=config.ollama.endpoint,
        timeout=config.ollama.request_timeout_seconds,
    )
    gateway = OllamaGateway(
        client=raw_client,
        embedding_options=config.ollama.embedding_options or None,
    )
    sse_broker = SseBroker()
    pipeline = IngestionPipeline(
        deps=PipelineDeps(
            conn=conn,
            vector_store=vs,
            ollama=gateway,
            embedding_model=config.ollama.embedding_model,
            broker=sse_broker,
        )
    )
    retrieval = RetrievalService(
        conn=conn,
        vector_store=vs,
        ollama=gateway,
        embedding_model=config.ollama.embedding_model,
    )
    generation = GenerationService(deps=GenerationDeps(retrieval=retrieval, ollama=gateway))
    recordings = RecordingRegistry()
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
    )

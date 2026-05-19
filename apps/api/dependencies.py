from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from functools import lru_cache

from core.config import AppConfig
from core.ingestion.pipeline import IngestionPipeline, PipelineDeps
from core.ollama.client import OllamaClient
from core.ollama.gateway import OllamaGateway
from core.storage.database import connect, migrate
from core.storage.vector_store import VectorStore

from apps.api.sse import SseBroker


_EMBEDDING_DIM = 1024  # bge-m3


@dataclass
class AppContext:
    config: AppConfig
    conn: sqlite3.Connection
    vector_store: VectorStore
    ollama: OllamaGateway
    sse: SseBroker
    pipeline: IngestionPipeline


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
    gateway = OllamaGateway(client=raw_client)
    pipeline = IngestionPipeline(deps=PipelineDeps(
        conn=conn,
        vector_store=vs,
        ollama=gateway,
        embedding_model=config.ollama.embedding_model,
    ))
    return AppContext(
        config=config,
        conn=conn,
        vector_store=vs,
        ollama=gateway,
        sse=SseBroker(),
        pipeline=pipeline,
    )

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Protocol

from core.exceptions import AppError, ErrorCode
from core.ids import new_id
from core.ingestion.chunker import chunk_document
from core.ingestion.parsers import get_parser
from core.logging import get_logger
from core.storage.chunks_repo import ChunkRecord, insert_chunks
from core.storage.sources_repo import SourceStatus, get_source, update_source_status
from core.storage.vector_store import ChunkVector, VectorStore

log = get_logger("ingestion.pipeline")


class _GatewayLike(Protocol):
    async def embed(self, *, model: str, text: str) -> list[float]: ...


class _BrokerLike(Protocol):
    async def publish(self, topic: str, payload: dict[str, Any]) -> None: ...


@dataclass
class PipelineDeps:
    conn: sqlite3.Connection
    vector_store: VectorStore
    ollama: _GatewayLike
    embedding_model: str
    broker: _BrokerLike | None = None


class IngestionPipeline:
    def __init__(self, *, deps: PipelineDeps) -> None:
        self._deps = deps

    async def run(self, *, source_id: str, kind: str, data: bytes) -> None:
        conn = self._deps.conn

        async def _publish(status: SourceStatus, **extra: Any) -> None:
            if self._deps.broker is None:
                return
            notebook_id = get_source(conn, source_id).notebook_id
            await self._deps.broker.publish(
                f"notebook:{notebook_id}",
                {"source_id": source_id, "status": status.value, **extra},
            )

        try:
            update_source_status(conn, source_id, status=SourceStatus.PARSING)
            await _publish(SourceStatus.PARSING)
            parser = get_parser(kind)
            doc = parser.parse_bytes(data, source_hint=get_source(conn, source_id).origin)

            update_source_status(conn, source_id, status=SourceStatus.CHUNKING, title=doc.title)
            await _publish(SourceStatus.CHUNKING)
            chunk_outs = chunk_document(doc)
            if not chunk_outs:
                raise AppError(
                    code=ErrorCode.INGESTION_PARSE_FAILED,
                    message="no chunks produced",
                )

            src = get_source(conn, source_id)
            chunk_records = [
                ChunkRecord(
                    id=new_id(),
                    source_id=source_id,
                    notebook_id=src.notebook_id,
                    ord=c.ord,
                    page=c.page,
                    heading_path=" > ".join(c.heading_path) if c.heading_path else None,
                    text=c.text,
                    token_count=c.token_count,
                )
                for c in chunk_outs
            ]
            insert_chunks(conn, chunk_records)

            update_source_status(conn, source_id, status=SourceStatus.EMBEDDING)
            await _publish(SourceStatus.EMBEDDING)
            vectors: list[ChunkVector] = []
            for rec in chunk_records:
                vec = await self._deps.ollama.embed(model=self._deps.embedding_model, text=rec.text)
                vectors.append(
                    ChunkVector(
                        id=rec.id,
                        vector=vec,
                        notebook_id=rec.notebook_id,
                        source_id=rec.source_id,
                        source_kind=kind,
                        page=rec.page,
                        heading_path=rec.heading_path,
                        ord=rec.ord,
                    )
                )
            self._deps.vector_store.upsert(vectors)

            page_count = max((c.page or 0 for c in chunk_outs), default=0) or None
            update_source_status(
                conn,
                source_id,
                status=SourceStatus.READY,
                chunk_count=len(chunk_records),
                page_count=page_count,
            )
            await _publish(SourceStatus.READY, chunk_count=len(chunk_records))
            log.info(
                "ingestion_complete",
                source_id=source_id,
                chunk_count=len(chunk_records),
            )

        except AppError as exc:
            update_source_status(conn, source_id, status=SourceStatus.ERROR, error_msg=exc.message)
            await _publish(SourceStatus.ERROR, error_msg=exc.message)
            log.error("ingestion_failed", source_id=source_id, code=exc.code, error=exc.message)
        except Exception as exc:  # last-resort safety
            update_source_status(conn, source_id, status=SourceStatus.ERROR, error_msg=str(exc))
            await _publish(SourceStatus.ERROR, error_msg=str(exc))
            log.exception("ingestion_unexpected", source_id=source_id)

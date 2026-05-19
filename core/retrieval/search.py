from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Protocol

from core.storage.chunks_repo import get_chunks_by_ids
from core.storage.sources_repo import get_source
from core.storage.vector_store import VectorStore


class _GatewayLike(Protocol):
    async def embed(self, *, model: str, text: str) -> list[float]: ...


@dataclass
class RetrievedChunk:
    chunk_id: str
    source_id: str
    source_title: str
    source_kind: str
    page: int | None
    heading_path: str | None
    ord: int
    text: str
    token_count: int
    score: float


class RetrievalService:
    def __init__(
        self,
        *,
        conn: sqlite3.Connection,
        vector_store: VectorStore,
        ollama: _GatewayLike,
        embedding_model: str,
    ) -> None:
        self._conn = conn
        self._vs = vector_store
        self._ollama = ollama
        self._embedding_model = embedding_model

    async def search(
        self,
        *,
        notebook_id: str,
        query: str,
        limit: int,
    ) -> list[RetrievedChunk]:
        if not query.strip():
            return []
        qvec = await self._ollama.embed(model=self._embedding_model, text=query)
        hits = self._vs.search(query=qvec, notebook_id=notebook_id, limit=limit)
        if not hits:
            return []
        records = get_chunks_by_ids(self._conn, [h.id for h in hits])
        score_by_id = {h.id: h.score for h in hits}

        # cache source titles to avoid N+1
        title_cache: dict[str, str] = {}

        def _title(src_id: str) -> str:
            if src_id not in title_cache:
                src = get_source(self._conn, src_id)
                title_cache[src_id] = src.title or (src.origin or "untitled")
            return title_cache[src_id]

        kind_by_chunk = {h.id: h.source_kind for h in hits}

        return [
            RetrievedChunk(
                chunk_id=rec.id,
                source_id=rec.source_id,
                source_title=_title(rec.source_id),
                source_kind=kind_by_chunk.get(rec.id, ""),
                page=rec.page,
                heading_path=rec.heading_path,
                ord=rec.ord,
                text=rec.text,
                token_count=rec.token_count,
                score=score_by_id.get(rec.id, 0.0),
            )
            for rec in records
        ]

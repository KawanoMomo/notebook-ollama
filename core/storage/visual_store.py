"""ページ視覚埋め込みの第2コレクション pages_visual (Stage 3, spec §5)。

chunks コレクション(vector_store.py)とは別コレクションだが、Qdrant ローカル
モードの 1 パス 1 クライアント制約のため QdrantClient は共有する。
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

VISUAL_COLLECTION = "pages_visual"

_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def _page_point_id(source_id: str, page: int) -> str:
    return str(uuid.uuid5(_NS, f"visualpage:{source_id}:{page}"))


@dataclass
class PageVector:
    source_id: str
    page: int
    vector: list[float]
    notebook_id: str
    embedding_model: str
    built_at: str


@dataclass
class PageHit:
    source_id: str
    page: int
    score: float


class VisualPageStore:
    def __init__(self, *, client: QdrantClient) -> None:
        self._client = client

    def _exists(self) -> bool:
        existing = {c.name for c in self._client.get_collections().collections}
        return VISUAL_COLLECTION in existing

    def ensure_collection(self, *, dim: int) -> None:
        if self._exists():
            return
        self._client.create_collection(
            collection_name=VISUAL_COLLECTION,
            vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
        )

    def collection_dim(self) -> int | None:
        if not self._exists():
            return None
        info = self._client.get_collection(VISUAL_COLLECTION)
        return info.config.params.vectors.size

    def upsert_pages(self, vectors: Iterable[PageVector]) -> None:
        points = [
            qm.PointStruct(
                id=_page_point_id(v.source_id, v.page),
                vector=v.vector,
                payload={
                    "source_id": v.source_id,
                    "page": v.page,
                    "notebook_id": v.notebook_id,
                    "embedding_model": v.embedding_model,
                    "built_at": v.built_at,
                },
            )
            for v in vectors
        ]
        self._client.upsert(collection_name=VISUAL_COLLECTION, points=points)

    def search(self, *, query: list[float], notebook_id: str, limit: int) -> list[PageHit]:
        if not self._exists():
            return []
        result = self._client.query_points(
            collection_name=VISUAL_COLLECTION,
            query=query,
            query_filter=qm.Filter(
                must=[qm.FieldCondition(key="notebook_id", match=qm.MatchValue(value=notebook_id))]
            ),
            limit=limit,
        )
        hits: list[PageHit] = []
        for p in result.points:
            payload = p.payload or {}
            hits.append(
                PageHit(
                    source_id=payload.get("source_id", ""),
                    page=int(payload.get("page", 0)),
                    score=p.score,
                )
            )
        return hits

    def delete_by_source(self, source_id: str) -> None:
        if not self._exists():
            return
        self._client.delete(
            collection_name=VISUAL_COLLECTION,
            points_selector=qm.Filter(
                must=[qm.FieldCondition(key="source_id", match=qm.MatchValue(value=source_id))]
            ),
        )

    def delete_by_notebook(self, notebook_id: str) -> None:
        if not self._exists():
            return
        self._client.delete(
            collection_name=VISUAL_COLLECTION,
            points_selector=qm.Filter(
                must=[qm.FieldCondition(key="notebook_id", match=qm.MatchValue(value=notebook_id))]
            ),
        )

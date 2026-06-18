from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

COLLECTION = "chunks"

# Namespace for deterministic UUID derivation from arbitrary string IDs
_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # uuid.NAMESPACE_URL


def _to_point_id(id_str: str) -> str:
    """Convert an arbitrary string ID to a UUID string for Qdrant.

    Qdrant local mode only accepts UUID or unsigned-int point IDs.
    We derive a deterministic UUID-v5 from the original string and
    store the original in the payload under 'orig_id'.
    """
    return str(uuid.uuid5(_NS, id_str))


@dataclass
class ChunkVector:
    id: str
    vector: list[float]
    notebook_id: str
    source_id: str
    source_kind: str
    page: int | None
    heading_path: str | None
    ord: int
    start_ms: int | None = None
    end_ms: int | None = None
    speaker: str | None = None
    channel: str | None = None


@dataclass
class SearchHit:
    id: str
    score: float
    notebook_id: str
    source_id: str
    source_kind: str
    page: int | None
    heading_path: str | None
    ord: int
    start_ms: int | None = None
    end_ms: int | None = None
    speaker: str | None = None
    channel: str | None = None


class VectorStore:
    def __init__(self, *, path: Path, dim: int) -> None:
        path.mkdir(parents=True, exist_ok=True)
        self._client = QdrantClient(path=str(path))
        self._dim = dim

    def ensure_collection(self) -> None:
        existing = {c.name for c in self._client.get_collections().collections}
        if COLLECTION in existing:
            return
        self._client.create_collection(
            collection_name=COLLECTION,
            vectors_config=qm.VectorParams(size=self._dim, distance=qm.Distance.COSINE),
        )

    def upsert(self, vectors: Iterable[ChunkVector]) -> None:
        points = [
            qm.PointStruct(
                id=_to_point_id(v.id),
                vector=v.vector,
                payload={
                    "orig_id": v.id,
                    "notebook_id": v.notebook_id,
                    "source_id": v.source_id,
                    "source_kind": v.source_kind,
                    "page": v.page,
                    "heading_path": v.heading_path,
                    "ord": v.ord,
                    "start_ms": v.start_ms,
                    "end_ms": v.end_ms,
                    "speaker": v.speaker,
                    "channel": v.channel,
                },
            )
            for v in vectors
        ]
        self._client.upsert(collection_name=COLLECTION, points=points)

    def search(
        self,
        *,
        query: list[float],
        notebook_id: str,
        limit: int,
    ) -> list[SearchHit]:
        result = self._client.query_points(
            collection_name=COLLECTION,
            query=query,
            query_filter=qm.Filter(
                must=[qm.FieldCondition(key="notebook_id", match=qm.MatchValue(value=notebook_id))]
            ),
            limit=limit,
        )
        hits: list[SearchHit] = []
        for p in result.points:
            payload = p.payload or {}
            hits.append(
                SearchHit(
                    id=payload.get("orig_id", str(p.id)),
                    score=p.score,
                    notebook_id=payload.get("notebook_id", ""),
                    source_id=payload.get("source_id", ""),
                    source_kind=payload.get("source_kind", ""),
                    page=payload.get("page"),
                    heading_path=payload.get("heading_path"),
                    ord=payload.get("ord", 0),
                    start_ms=payload.get("start_ms"),
                    end_ms=payload.get("end_ms"),
                    speaker=payload.get("speaker"),
                    channel=payload.get("channel"),
                )
            )
        return hits

    def delete_by_source(self, source_id: str) -> None:
        self._client.delete(
            collection_name=COLLECTION,
            points_selector=qm.Filter(
                must=[qm.FieldCondition(key="source_id", match=qm.MatchValue(value=source_id))]
            ),
        )

    def close(self) -> None:
        self._client.close()

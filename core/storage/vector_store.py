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
        self._path = path
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

    def collection_dim(self) -> int | None:
        """現行 collection のベクトル次元。collection が無ければ None。"""
        existing = {c.name for c in self._client.get_collections().collections}
        if COLLECTION not in existing:
            return None
        info = self._client.get_collection(COLLECTION)
        return info.config.params.vectors.size

    def recreate_collection(self, dim: int) -> None:
        """既存 collection を drop してから dim 次元(COSINE)で作り直す。

        全チャンクの再インデックス用。既存 collection が無くても新規作成する。
        以降この VectorStore は新しい dim で動作する。

        qdrant local mode は SQLite ベースのストレージを保持するため、
        close してから SQLite ファイルを削除して再オープン・再作成することで
        完全なリセットを保証する。Windows でファイルロックが残らないよう
        delete_collection 前に close する。
        """
        import shutil

        # close して Windows のファイルロックを解放してから削除する
        self._client.close()
        col_dir = self._path / "collection" / COLLECTION
        if col_dir.exists():
            shutil.rmtree(col_dir)
        self._client = QdrantClient(path=str(self._path))
        # meta.json から collection エントリを削除する
        existing = {c.name for c in self._client.get_collections().collections}
        if COLLECTION in existing:
            self._client.delete_collection(collection_name=COLLECTION)
        self._client.create_collection(
            collection_name=COLLECTION,
            vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
        )
        self._dim = dim

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
        source_ids: list[str] | None = None,
    ) -> list[SearchHit]:
        must: list[qm.Condition] = [
            qm.FieldCondition(key="notebook_id", match=qm.MatchValue(value=notebook_id))
        ]
        if source_ids:
            must.append(
                qm.FieldCondition(key="source_id", match=qm.MatchAny(any=source_ids))
            )
        result = self._client.query_points(
            collection_name=COLLECTION,
            query=query,
            query_filter=qm.Filter(must=must),
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

    def export_channels(self) -> dict[str, str | None]:
        """既存 collection の全点を走査し {orig_id: channel} を返す。

        channel は vector-store payload 専用フィールド(SQLite には無い)で、
        再インデックス時に list_chunks_for_source からは復元できない。recreate
        前に本メソッドで現行 collection から退避し、再 upsert 時に carry-forward
        することで録音引用の audio channel(mic/system)を保持する。
        collection が無ければ空 dict。
        """
        existing = {c.name for c in self._client.get_collections().collections}
        if COLLECTION not in existing:
            return {}
        out: dict[str, str | None] = {}
        offset: object | None = None
        while True:
            records, offset = self._client.scroll(
                collection_name=COLLECTION,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for rec in records:
                payload = rec.payload or {}
                orig_id = payload.get("orig_id")
                if orig_id is not None:
                    out[orig_id] = payload.get("channel")
            if offset is None:
                break
        return out

    def rename_speaker(self, source_id: str, from_label: str, to_label: str) -> None:
        """Update the ``speaker`` payload for all points of one source's label.

        Filters on ``source_id`` AND ``speaker == from_label`` (within-source
        scope, M4) and sets ``speaker = to_label``. Best-effort: SQLite is the
        source of truth, so payload-update failures are logged and swallowed
        (the speaker payload is only used for citation display, not filtering).
        """
        flt = qm.Filter(
            must=[
                qm.FieldCondition(key="source_id", match=qm.MatchValue(value=source_id)),
                qm.FieldCondition(key="speaker", match=qm.MatchValue(value=from_label)),
            ]
        )
        try:
            self._client.set_payload(
                collection_name=COLLECTION,
                payload={"speaker": to_label},
                points=flt,
            )
        except Exception as exc:  # pragma: no cover - best-effort, SQLite is source of truth
            import logging

            logging.getLogger(__name__).warning(
                "qdrant rename_speaker failed (source_id=%s, %r->%r): %s",
                source_id, from_label, to_label, exc,
            )

    def delete_by_source(self, source_id: str) -> None:
        self._client.delete(
            collection_name=COLLECTION,
            points_selector=qm.Filter(
                must=[qm.FieldCondition(key="source_id", match=qm.MatchValue(value=source_id))]
            ),
        )

    def close(self) -> None:
        self._client.close()

"""視覚埋め込みの第2インデックス (Stage 3 → Stage 4 で単位を一般化)。

chunks コレクション(vector_store.py)とは別コレクションだが、Qdrant ローカル
モードの 1 パス 1 クライアント制約のため QdrantClient は共有する。

Stage 4 で「索引の単位」を導入した:
  unit="page" -> pages_visual  (1ページ = 1ベクトル。Stage 3 と完全互換)
  unit="tile" -> tiles_visual  (ページをタイル分割し、1タイル = 1ベクトル)
両者は別コレクションなので同時に保持でき、設定の切替に再構築は要らない。
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

PAGE_COLLECTION = "pages_visual"
TILE_COLLECTION = "tiles_visual"

# Stage 3 の呼び出し元との後方互換
VISUAL_COLLECTION = PAGE_COLLECTION

_COLLECTION_BY_UNIT = {"page": PAGE_COLLECTION, "tile": TILE_COLLECTION}

_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def _unit_point_id(unit: str, source_id: str, page: int, tile_index: int | None) -> str:
    """決定的な点ID。

    unit="page" のシード文字列は Stage 3 と1文字も変えない — 変えると構築済みの
    pages_visual が全部ゴミになり再構築が必要になる。
    """
    if unit == "tile":
        return str(uuid.uuid5(_NS, f"visualtile:{source_id}:{page}:{tile_index}"))
    return str(uuid.uuid5(_NS, f"visualpage:{source_id}:{page}"))


@dataclass
class UnitVector:
    source_id: str
    page: int
    vector: list[float]
    notebook_id: str
    embedding_model: str
    built_at: str
    # unit="tile" のときのみ 0 始まりのタイル通し番号。page 単位では None。
    tile_index: int | None = None


@dataclass
class UnitHit:
    source_id: str
    page: int
    score: float
    tile_index: int | None = None


# Stage 3 の呼び出し元との後方互換エイリアス
PageVector = UnitVector
PageHit = UnitHit


class VisualUnitStore:
    def __init__(self, *, client: QdrantClient, unit: str = "page") -> None:
        if unit not in _COLLECTION_BY_UNIT:
            raise ValueError(f"unknown visual index unit: {unit!r}")
        self._client = client
        self._unit = unit
        self._collection = _COLLECTION_BY_UNIT[unit]

    @property
    def unit(self) -> str:
        return self._unit

    @property
    def collection(self) -> str:
        return self._collection

    def _exists(self) -> bool:
        existing = {c.name for c in self._client.get_collections().collections}
        return self._collection in existing

    def ensure_collection(self, *, dim: int) -> None:
        if self._exists():
            return
        self._client.create_collection(
            collection_name=self._collection,
            vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
        )

    def collection_dim(self) -> int | None:
        if not self._exists():
            return None
        info = self._client.get_collection(self._collection)
        return info.config.params.vectors.size

    def upsert_units(self, vectors: Iterable[UnitVector]) -> None:
        points = [
            qm.PointStruct(
                id=_unit_point_id(self._unit, v.source_id, v.page, v.tile_index),
                vector=v.vector,
                payload={
                    "source_id": v.source_id,
                    "page": v.page,
                    "tile_index": v.tile_index,
                    "notebook_id": v.notebook_id,
                    "embedding_model": v.embedding_model,
                    "built_at": v.built_at,
                },
            )
            for v in vectors
        ]
        self._client.upsert(collection_name=self._collection, points=points)

    # Stage 3 の呼び出し元との後方互換
    upsert_pages = upsert_units

    def search(self, *, query: list[float], notebook_id: str, limit: int) -> list[UnitHit]:
        if not self._exists():
            return []
        result = self._client.query_points(
            collection_name=self._collection,
            query=query,
            query_filter=qm.Filter(
                must=[qm.FieldCondition(key="notebook_id", match=qm.MatchValue(value=notebook_id))]
            ),
            limit=limit,
        )
        hits: list[UnitHit] = []
        for p in result.points:
            payload = p.payload or {}
            raw_tile = payload.get("tile_index")
            hits.append(
                UnitHit(
                    source_id=payload.get("source_id", ""),
                    page=int(payload.get("page", 0)),
                    score=p.score,
                    tile_index=(None if raw_tile is None else int(raw_tile)),
                )
            )
        return hits

    def delete_by_source(self, source_id: str) -> None:
        if not self._exists():
            return
        self._client.delete(
            collection_name=self._collection,
            points_selector=qm.Filter(
                must=[qm.FieldCondition(key="source_id", match=qm.MatchValue(value=source_id))]
            ),
        )

    def delete_by_notebook(self, notebook_id: str) -> None:
        if not self._exists():
            return
        self._client.delete(
            collection_name=self._collection,
            points_selector=qm.Filter(
                must=[qm.FieldCondition(key="notebook_id", match=qm.MatchValue(value=notebook_id))]
            ),
        )


class VisualPageStore(VisualUnitStore):
    """Stage 3 互換の薄いサブクラス(unit="page" 固定)。

    apps/api/routers/sources.py など「ページ索引を消す」意図の既存呼び出しを
    そのまま動かすために残す。新規コードは VisualUnitStore を使うこと。
    """

    def __init__(self, *, client: QdrantClient) -> None:
        super().__init__(client=client, unit="page")

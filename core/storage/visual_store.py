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

from core.visual.units import VISUAL_UNITS, VisualUnit

PAGE_COLLECTION = "pages_visual"
TILE_COLLECTION = "tiles_visual"

_COLLECTION_BY_UNIT: dict[VisualUnit, str] = {
    "page": PAGE_COLLECTION,
    "tile": TILE_COLLECTION,
}
# 語彙を増やしたらここも埋めること。VISUAL_UNITS との差分を起動時に検出する。
assert set(_COLLECTION_BY_UNIT) == set(VISUAL_UNITS), (
    "visual unit vocabulary and collection map are out of sync: "
    f"{sorted(set(VISUAL_UNITS) ^ set(_COLLECTION_BY_UNIT))}"
)

_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def _unit_point_id(unit: str, source_id: str, page: int, tile_index: int | None) -> str:
    """決定的な点ID。

    unit="page" のシード文字列は Stage 3 と1文字も変えない — 変えると構築済みの
    pages_visual が全部ゴミになり再構築が必要になる。
    """
    if unit == "tile":
        if tile_index is None:
            # そのまま通すとシードに文字列 "None" が埋まり、同一ページの全タイルが
            # 1点に潰れる(静かなデータ破損)。現在は _units_for_page が必ず int を
            # 返すので到達しないが、ID の生成は間違えたときの被害が大きいので
            # 落として気づけるようにしておく。
            raise ValueError("tile_index is required for unit='tile'")
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


class VisualUnitStore:
    def __init__(self, *, client: QdrantClient, unit: str = "page") -> None:
        if unit not in _COLLECTION_BY_UNIT:
            raise ValueError(f"unknown visual index unit: {unit!r}")
        self._client = client
        self._unit = unit
        self._collection = _COLLECTION_BY_UNIT[unit]
        # ensure_collection() の結果キャッシュ。構築ループが単位ごとに呼ぶため
        # (タイルなら1ページ3回)、毎回 get_collections() を叩かないようにする。
        self._ensured = False

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
        """コレクションが無ければ作る。作成済みならプロセス内キャッシュで即返す。

        構築ループは 1 単位ごとにこれを呼ぶ (タイルなら 1 ページあたり 3 回)。
        素直に毎回 `get_collections()` を叩くと、167 ページ × 3 タイルで 500 往復を
        Qdrant に投げることになる。作成はこのプロセスがやる操作なので、
        「作った/在ることを確認した」という事実はプロセス内で覚えてよい。

        キャッシュは「存在する」方向にしか倒さない。外部でコレクションを消された
        場合は upsert が失敗するが、それは元々 `_exists()` の確認と upsert の
        隙間でも起きうる競合で、キャッシュの有無で変わらない。
        """
        if self._ensured:
            return
        if not self._exists():
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
            )
        self._ensured = True

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

    def search(
        self,
        *,
        query: list[float],
        notebook_id: str,
        limit: int,
        source_ids: list[str] | None = None,
    ) -> list[UnitHit]:
        if not self._exists():
            return []
        must: list[qm.Condition] = [
            qm.FieldCondition(key="notebook_id", match=qm.MatchValue(value=notebook_id))
        ]
        if source_ids:
            # チャットのソース選択を視覚検索にも効かせる。これが無いと
            # visual_only / pixel_native は全結果が視覚ヒットなので、
            # UI で絞ったソース選択が完全に無視される(最終レビュー I5)。
            must.append(
                qm.FieldCondition(key="source_id", match=qm.MatchAny(any=source_ids))
            )
        result = self._client.query_points(
            collection_name=self._collection,
            query=query,
            query_filter=qm.Filter(must=must),
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

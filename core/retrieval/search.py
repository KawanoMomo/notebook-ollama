from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from core.logging import get_logger
from core.storage.chunks_repo import get_chunks_by_ids
from core.storage.sources_repo import get_source
from core.storage.vector_store import VectorStore

log = get_logger("retrieval")


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
    start_ms: int | None = None
    end_ms: int | None = None
    speaker: str | None = None
    channel: str | None = None
    via_visual: bool = False


@dataclass
class VisualSearchDeps:
    """視覚ページ検索の依存束(Stage 3)。enabled は「設定ON かつ ベータON かつ
    extra導入済み」の合成getterを配線側(apps/api/dependencies.py)が渡す。"""

    store: Any  # VisualPageStore
    encoder: Any  # VisualEncoder プロトコル
    enabled: Callable[[], bool]
    meta_lookup: Callable[[str], Any]  # notebook_id -> VisualIndexMeta | None
    model_name_getter: Callable[[], str]


class RetrievalService:
    def __init__(
        self,
        *,
        conn: sqlite3.Connection,
        vector_store: VectorStore,
        ollama: _GatewayLike,
        embedding_model: str,
        embedding_model_getter: Callable[[], str] | None = None,
        figure_desc_enabled: Callable[[], bool] | None = None,
        visual: VisualSearchDeps | None = None,
    ) -> None:
        self._conn = conn
        self._vs = vector_store
        self._ollama = ollama
        self._embedding_model = embedding_model
        self._embedding_model_getter = embedding_model_getter
        self._figure_desc_enabled = figure_desc_enabled
        self._visual = visual

    def _resolve_embedding_model(self) -> str:
        if self._embedding_model_getter is not None:
            return self._embedding_model_getter()
        return self._embedding_model

    def _source_title(self, source_id: str, cache: dict[str, str]) -> str:
        if source_id not in cache:
            src = get_source(self._conn, source_id)
            cache[source_id] = src.title or (src.origin or "untitled")
        return cache[source_id]

    async def search(
        self,
        *,
        notebook_id: str,
        query: str,
        limit: int,
        source_ids: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        if not query.strip():
            return []
        qvec = await self._ollama.embed(model=self._resolve_embedding_model(), text=query)
        hits = self._vs.search(
            query=qvec, notebook_id=notebook_id, limit=limit, source_ids=source_ids
        )
        # 早期return はしない: テキストヒットが0件でも視覚検索側だけで結果が
        # 得られる場合がある(視覚インデックスのみのページ等、spec §6)。
        records = get_chunks_by_ids(self._conn, [h.id for h in hits])
        if self._figure_desc_enabled is not None and not self._figure_desc_enabled():
            # ベータOFF時は図説明チャンクを検索から除外する(spec: 2026-07-20-
            # vlm-figure-ocr-design.md §提供形態。データ・ベクトルは保持し、
            # ONに戻せば再び検索に乗る)。
            records = [r for r in records if r.kind != "figure_desc"]
        score_by_id = {h.id: h.score for h in hits}

        # cache source titles to avoid N+1 (この search() 呼び出し内のみ有効)
        title_cache: dict[str, str] = {}

        kind_by_chunk = {h.id: h.source_kind for h in hits}
        hit_by_id = {h.id: h for h in hits}

        text_results = [
            RetrievedChunk(
                chunk_id=rec.id,
                source_id=rec.source_id,
                source_title=self._source_title(rec.source_id, title_cache),
                source_kind=kind_by_chunk.get(rec.id, ""),
                page=rec.page,
                heading_path=rec.heading_path,
                ord=rec.ord,
                text=rec.text,
                token_count=rec.token_count,
                score=score_by_id.get(rec.id, 0.0),
                start_ms=hit_by_id[rec.id].start_ms,
                end_ms=hit_by_id[rec.id].end_ms,
                # speaker は SQLite を正とする(話者リネームは SQLite を即時更新、
                # Qdrant payload 更新は best-effort なので、payload 由来だと
                # リネーム後に旧名が引用へ残りうる)。text と同じく rec から取る。
                speaker=rec.speaker,
                channel=hit_by_id[rec.id].channel,
            )
            for rec in records
        ]

        visual_results = await self._visual_hits(
            notebook_id=notebook_id, query=query, text_results=text_results,
            limit=limit, title_cache=title_cache,
        )
        if not visual_results:
            return text_results
        merged = text_results + visual_results
        # RRFスコア降順に整列して limit で切る。text_results/visual_results の
        # score には既にRRFスコアが入っている(_visual_hits 参照)
        merged.sort(key=lambda h: h.score, reverse=True)
        return merged[:limit]

    async def _visual_hits(
        self,
        *,
        notebook_id: str,
        query: str,
        text_results: list[RetrievedChunk],
        limit: int,
        title_cache: dict[str, str],
    ) -> list[RetrievedChunk]:
        """視覚ページ検索→RRF→ページ→チャンク展開。実行条件を満たさない/
        失敗した場合は [] を返し、呼び出し側はテキストのみで応答する(spec §9)。
        戻り値の score はRRFスコア。text_results の score もRRFスコアに
        書き換える(融合順位はRRF基準、spec §6)。"""
        from core.retrieval.fusion import rrf_fuse
        from core.storage.chunks_repo import list_text_chunks_for_page

        v = self._visual
        if v is None:
            return []
        try:
            if not v.enabled():
                return []
            meta = v.meta_lookup(notebook_id)
            if meta is None or meta.embedding_model != v.model_name_getter():
                return []
            qvec = await v.encoder.embed_text(text=query)
            page_hits = v.store.search(query=qvec, notebook_id=notebook_id, limit=limit)
            if not page_hits:
                return []
            fused = rrf_fuse(text_hits=text_results, visual_hits=page_hits)
            # テキスト側のscoreをRRFスコアへ書き換え(融合ソートの物差しを揃える)
            for chunk, rrf_score in fused.ordered_text:
                chunk.score = rrf_score
            seen_ids = {c.chunk_id for c in text_results}
            out: list[RetrievedChunk] = []
            for page_hit, rrf_score in fused.surviving_pages:
                chunks = list_text_chunks_for_page(
                    self._conn, page_hit.source_id, page_hit.page, 2
                )
                if chunks:
                    for rec in chunks:
                        if rec.id in seen_ids:
                            continue
                        seen_ids.add(rec.id)
                        out.append(RetrievedChunk(
                            chunk_id=rec.id, source_id=rec.source_id,
                            source_title=self._source_title(rec.source_id, title_cache),
                            source_kind="pdf", page=rec.page,
                            heading_path=rec.heading_path, ord=rec.ord,
                            text=rec.text, token_count=rec.token_count,
                            score=rrf_score, via_visual=True,
                        ))
                else:
                    # スキャン未OCRページ: 説明なしのページ画像のみ(spec §6)
                    out.append(RetrievedChunk(
                        chunk_id=f"vp:{page_hit.source_id}:{page_hit.page}",
                        source_id=page_hit.source_id,
                        source_title=self._source_title(page_hit.source_id, title_cache),
                        source_kind="pdf", page=page_hit.page, heading_path=None,
                        ord=0,
                        text=f"(視覚検索ヒット p.{page_hit.page}: "
                             "このページはテキスト未抽出です。ページ画像を参照)",
                        token_count=30, score=rrf_score, via_visual=True,
                    ))
            return out
        except Exception:
            log.warning("visual_search_failed", notebook_id=notebook_id, exc_info=True)
            return []

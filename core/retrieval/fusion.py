"""テキスト検索と視覚ページ検索の RRF 融合 (Stage 3, spec §6)。

純関数。ページ→チャンク展開はDBアクセスが要るため RetrievalService 側
(search.py)で行い、ここは順位融合と重複排除のみを担う。
"""
from __future__ import annotations

from dataclasses import dataclass

from core.retrieval.search import RetrievedChunk
from core.storage.visual_store import PageHit

RRF_K = 60


@dataclass
class FusionResult:
    ordered_text: list[tuple[RetrievedChunk, float]]
    surviving_pages: list[tuple[PageHit, float]]


def rrf_fuse(
    *,
    text_hits: list[RetrievedChunk],
    visual_hits: list[PageHit],
    k: int = RRF_K,
) -> FusionResult:
    text_scored = [(c, 1.0 / (k + rank)) for rank, c in enumerate(text_hits, start=1)]
    text_pages = {(c.source_id, c.page) for c in text_hits if c.page is not None}
    pages_scored = [
        (p, 1.0 / (k + rank))
        for rank, p in enumerate(visual_hits, start=1)
        # 同一ページにテキスト・視覚の両方でヒットした場合は視覚側を吸収
        if (p.source_id, p.page) not in text_pages
    ]
    return FusionResult(ordered_text=text_scored, surviving_pages=pages_scored)

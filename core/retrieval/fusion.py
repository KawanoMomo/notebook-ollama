"""テキスト検索と視覚ページ検索の RRF 融合 (Stage 3, spec §6)。

純関数。ページ→チャンク展開はDBアクセスが要るため RetrievalService 側
(search.py)で行い、ここは順位融合と重複排除のみを担う。
"""
from __future__ import annotations

from dataclasses import dataclass

from core.retrieval.search import RetrievedChunk
from core.storage.visual_store import UnitHit

RRF_K = 60


@dataclass
class FusionResult:
    ordered_text: list[tuple[RetrievedChunk, float]]
    surviving_pages: list[tuple[UnitHit, float]]


def collapse_to_best_per_page(hits: list[UnitHit]) -> list[UnitHit]:
    """同一 (source_id, page) の複数タイルヒットを最上位1件に畳む (Stage 4)。

    タイル索引では1ページから複数タイルが上位に入りうる。畳まないと
      - ページ→チャンク展開が同じチャンクを何度も引く(seen_ids で捨てられる)
      - 1ページが limit の枠を食い潰してページ多様性が落ちる
      - 引用が同じページで重複する
    の3つが同時に起きる。呼び出し側は over-fetch(limit x タイル数)してから
    この関数を通し、改めて limit 件に切ること。

    入力はスコア降順である前提(Qdrant の検索結果はそうなっている)。
    順序は保ち、各ページの最初に現れたヒット(=最上位タイル)だけを残す。
    unit="page" のヒット列に対しては恒等関数として振る舞う。
    """
    seen: set[tuple[str, int]] = set()
    out: list[UnitHit] = []
    for h in hits:
        key = (h.source_id, h.page)
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out


def rrf_fuse(
    *,
    text_hits: list[RetrievedChunk],
    visual_hits: list[UnitHit],
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

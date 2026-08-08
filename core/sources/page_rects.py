"""原本ページ上の矩形の決定。

設計: docs/specs/2026-08-07-citation-evidence-ui-design.md §3.4

表・図チャンクは取込時に Markdown 化されて原本に存在しないため、`search_for` は
原理的に空振りする。取込済みアセットの bbox を流用する方が精度も高い。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pymupdf

_POINTS_PER_INCH = 72.0
# 単語単位フォールバックで、この長さ未満の語は無視する
# (前置詞や冠詞まで拾うとページ中が枠だらけになる)。
_MIN_WORD_CHARS = 4


@dataclass(frozen=True)
class Rect:
    """PNG のピクセル座標系での矩形。"""

    x: float
    y: float
    w: float
    h: float


def _scale(dpi: int) -> float:
    """PDF 座標(72dpi 基準)→ PNG ピクセルの倍率。"""
    return dpi / _POINTS_PER_INCH


def rects_from_asset_bbox(bbox_json: str | None, dpi: int) -> list[Rect]:
    """取込済みアセットの bbox をそのまま矩形にする。"""
    if not bbox_json:
        return []
    try:
        raw = json.loads(bbox_json)
    except (TypeError, ValueError):
        return []
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return []
    try:
        x0, y0, x1, y1 = (float(v) for v in raw)
    except (TypeError, ValueError):
        return []
    s = _scale(dpi)
    return [Rect(x=x0 * s, y=y0 * s, w=(x1 - x0) * s, h=(y1 - y0) * s)]


def _to_rects(found: list, dpi: int) -> list[Rect]:
    s = _scale(dpi)
    return [
        Rect(x=r.x0 * s, y=r.y0 * s, w=(r.x1 - r.x0) * s, h=(r.y1 - r.y0) * s) for r in found
    ]


def rects_from_quote(pdf_path: Path, page: int, quote: str, dpi: int) -> list[Rect]:
    """quote に対応する矩形。全体一致 → 単語単位の順に試し、駄目なら空。"""
    text = " ".join(quote.split())
    if not text:
        return []
    with pymupdf.open(pdf_path) as doc:
        if page < 1 or page > doc.page_count:
            return []
        pg = doc[page - 1]
        found = pg.search_for(text)
        if found:
            return _to_rects(found, dpi)
        # 行末ハイフネーションや抽出順のズレで全体一致しないことがある。
        # 単語単位で拾って和を取る(フォールバックは一段だけ)。
        pieces: list = []
        for word in text.split(" "):
            if len(word) < _MIN_WORD_CHARS:
                continue
            pieces.extend(pg.search_for(word))
        return _to_rects(pieces, dpi)

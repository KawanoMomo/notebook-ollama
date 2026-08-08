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
# 日本語の部分一致で使う窓幅。短すぎるとページ中が枠だらけになる。
_CJK_WINDOW = 12


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


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x3040 <= code <= 0x30FF  # かな
        or 0x4E00 <= code <= 0x9FFF  # 漢字
        or 0x3400 <= code <= 0x4DBF
    )


def _pieces_for_fallback(text: str) -> list[str]:
    """全体一致しなかったときに試す部分文字列(正規化済みテキスト用)。

    英語は単語単位。日本語は語境界が無いので固定長の窓で切り出す。
    """
    if sum(1 for c in text if _is_cjk(c)) >= len(text) * 0.3:
        return [
            text[i : i + _CJK_WINDOW]
            for i in range(0, max(1, len(text) - _CJK_WINDOW + 1), _CJK_WINDOW)
        ]
    return [w for w in text.split(" ") if len(w) >= _MIN_WORD_CHARS]


def _original_lines(quote: str) -> list[str]:
    """quote を元の改行で分けた行。

    PDF 抽出由来の quote の改行は、そのまま原本の行区切りに対応する。
    search_for は行をまたぐ日本語文字列をまず見つけられない(実測: 行単位なら
    全行ヒットするのに、連結すると 0 件)ため、行単位が最も当たる。
    """
    return [ln.strip() for ln in quote.splitlines() if len(ln.strip()) >= _MIN_WORD_CHARS]


def rects_from_quote(pdf_path: Path, page: int, quote: str, dpi: int) -> list[Rect]:
    """quote に対応する矩形。全体一致 → 部分一致の順に試し、駄目なら空。

    PDF 抽出由来の quote には改行が混じる。英語は空白へ畳めばよいが、
    日本語は本文に空白が無いため、空白を入れると一致しなくなる。
    そこで「空白へ畳んだ形」と「空白を除いた形」の両方を試す。
    """
    spaced = " ".join(quote.split())
    squeezed = "".join(quote.split())
    if not squeezed:
        return []
    with pymupdf.open(pdf_path) as doc:
        if page < 1 or page > doc.page_count:
            return []
        pg = doc[page - 1]
        for candidate in (spaced, squeezed):
            found = pg.search_for(candidate)
            if found:
                return _to_rects(found, dpi)
        # 行末ハイフネーションや抽出順のズレで全体一致しないことがある。
        # 部分一致で拾って和を取る(フォールバックは一段だけ)。
        # 1段目: 元の改行で割った行。日本語で最も当たる(行をまたぐ検索は通らない)。
        pieces: list = []
        for line in _original_lines(quote):
            pieces.extend(pg.search_for(line))
        if pieces:
            return _to_rects(pieces, dpi)
        # 2段目: 単語 / 固定長窓。英語の行末ハイフネーション等はこちらで拾う。
        for base in (squeezed, spaced):
            pieces = []
            for piece in _pieces_for_fallback(base):
                pieces.extend(pg.search_for(piece))
            if pieces:
                return _to_rects(pieces, dpi)
        return []

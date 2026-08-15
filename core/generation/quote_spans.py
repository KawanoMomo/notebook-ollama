"""β: LLM に併記させた根拠原文(<q>…</q>)からスパンを作る。

設計: docs/specs/2026-08-07-citation-evidence-ui-design.md §3.6

言語跨ぎ(英語ソースへの日本語回答)では字句照合(第1段)が原理的に効かないため、
これが「根拠」を示せる唯一の経路。既定 OFF で、OFF のときこのモジュールは呼ばれない。
"""

from __future__ import annotations

import re
from typing import Any

from core.generation.evidence_spans import iter_claim_occurrences, mask_code_regions

_QUOTE_RE = re.compile(r"<q>(.*?)</q>", re.DOTALL)
_CITATION_RE = re.compile(r"\[\^(\d+)\]")


def strip_quote_tags(answer: str) -> str:
    """表示用にタグだけ落とす(中身は残す)。"""
    return _QUOTE_RE.sub(lambda m: m.group(1), answer)


def _marker_positions(answer: str) -> list[int]:
    """各 [^n] の終端位置。コード領域内のマーカーは数えない。

    mask_code_regions はオフセットを保存するので、ここで得た位置はそのまま
    元テキストに使える(= iter_claim_occurrences の出現順と一致する)。
    """
    masked = mask_code_regions(answer)
    return [m.end() for m in _CITATION_RE.finditer(masked)]


def attach_quote_spans(
    *,
    answer: str,
    citations: list[dict[str, Any]],
    chunk_texts: dict[str, str],
) -> list[dict[str, Any]]:
    """各 [^n] の直前にある <q> の中身をチャンク本文で完全一致検索して spans を付ける。

    見つからない出現には spans を付けない(呼び出し側が第1段へフォールバックする)。
    """
    positions = _marker_positions(answer)
    spans_by_n: dict[int, list[dict[str, Any]]] = {}

    for occ in iter_claim_occurrences(answer):
        if occ.answer_occurrence >= len(positions):
            continue
        # 探索窓は「直前のマーカーの終端」から「このマーカーの終端」まで。
        # 単純に先頭からの最後の <q> を採ると、前の主張の引用が次の出現へ漏れる。
        window_start = positions[occ.answer_occurrence - 1] if occ.answer_occurrence > 0 else 0
        head = answer[window_start : positions[occ.answer_occurrence]]
        found = _QUOTE_RE.findall(head)
        if not found:
            continue
        quote = found[-1].strip()
        if not quote:
            continue

        citation = next((c for c in citations if c.get("n") == occ.n), None)
        if citation is None:
            continue
        text = chunk_texts.get(citation.get("chunk_id", ""))
        if not text:
            continue
        start = text.find(quote)
        if start < 0:
            # LLM が原文を writing し損ねた(言い換えた/幻覚した)。黙って諦め、
            # 呼び出し側の第1段フォールバックに委ねる。
            continue

        bucket = spans_by_n.setdefault(occ.n, [])
        bucket.append(
            {
                "answer_occurrence": occ.answer_occurrence,
                "ordinal": len(bucket) + 1,
                "start": start,
                "end": start + len(quote),
                "quote": quote,
                "method": "quote",
            }
        )

    return [{**c, "spans": spans_by_n.get(c.get("n"), [])} for c in citations]

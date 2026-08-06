"""検索精度メトリクス。

自前指標 (recall@k / MRR) は Ragas と独立に動き、Ragas 側の閾値設定ミスで
全条件が同スコアに潰れた場合の切り分けに使う (spec §6)。
"""

from __future__ import annotations

from difflib import SequenceMatcher

# 文字列類似度の既定閾値。全モジュールでこの値を共有する。
DEFAULT_THRESHOLD = 0.6


def _normalize(text: str) -> str:
    """空白の揺れを吸収する。改行・全角空白・連続空白を単一空白に潰す。"""
    return " ".join(text.replace("　", " ").split())


def matches(
    retrieved: str, reference: str, *, threshold: float = DEFAULT_THRESHOLD
) -> bool:
    """検索結果チャンクが正解チャンクと同一とみなせるか。"""
    a, b = _normalize(retrieved), _normalize(reference)
    if not a or not b:
        return False
    if a == b:
        return True
    # 正解チャンクが検索結果の一部として含まれる場合も一致とみなす
    # (チャンク境界のずれで前後に余分な文が付くケース)。
    if b in a or a in b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= threshold


def recall_at_k(
    retrieved: list[str],
    reference: list[str],
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> float:
    """正解チャンクのうち、検索結果に現れた割合。"""
    if not retrieved or not reference:
        return 0.0

    hit = sum(
        1
        for ref in reference
        if any(matches(r, ref, threshold=threshold) for r in retrieved)
    )
    return hit / len(reference)


def mrr(
    retrieved: list[str],
    reference: list[str],
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> float:
    """最初に正解が現れた順位の逆数。どの正解でもよい。"""
    if not retrieved or not reference:
        return 0.0

    for rank, r in enumerate(retrieved, 1):
        if any(matches(r, ref, threshold=threshold) for ref in reference):
            return 1.0 / rank
    return 0.0

"""根拠スパン解決 第2段 — 主張文⇔文の埋め込み類似(バッジ押下時のみ実行)。

設計: docs/specs/2026-08-07-citation-evidence-ui-design.md §3.1.2
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Protocol

from core.generation.evidence_spans import cjk_ratio

# 結合の下限。日本語の普通の短文(「これは一文目である。」= 10文字)を潰さない値。
MIN_SENTENCE_CHARS = 8

# 文境界:
#   - 和文の句点類の直後
#   - ASCII の . ! ? の直後で、空白を挟んで「大文字か開き括弧」が続くもの
#   - 改行
# 略語・小数を割らないための条件が「次が大文字」。`Fig. 3` は次が数字、`e.g. foo` は
# 次が小文字なので、いずれも境界にならない。`details. The` は境界になる。
_BOUNDARY_RE = re.compile(
    r"(?<=[。．!?！？])"
    r"|(?<=[.!?])(?=\s+[A-Z(\[\"'])"
    r"|\n"
)

# 「次が大文字」だけでは略語を割ってしまう(`e.g. Sleep` `Fig. 3-1` `No. 5` など)。
# ピリオド直前の語がこれらなら文境界にしない。技術文書に頻出するものを列挙する。
_ABBREVIATIONS = frozenset(
    {
        "e.g.", "i.e.", "cf.", "vs.", "etc.", "al.",
        "fig.", "figs.", "no.", "nos.", "eq.", "eqs.", "sec.", "secs.",
        "ch.", "ref.", "refs.", "tab.", "vol.", "pp.", "approx.",
        "dr.", "mr.", "mrs.", "ms.", "prof.", "st.", "inc.", "ltd.", "co.",
    }
)
# ピリオドの直前にある「単語らしきもの」を取る(略語判定用)。
_TRAILING_TOKEN_RE = re.compile(r"([A-Za-z][A-Za-z.]*\.)$")


def _is_abbreviation_boundary(text: str, pos: int) -> bool:
    """pos(境界候補=ピリオドの直後)が略語の途中かどうか。"""
    m = _TRAILING_TOKEN_RE.search(text[:pos])
    if m is None:
        return False
    return m.group(1).lower() in _ABBREVIATIONS


@dataclass(frozen=True)
class Sentence:
    text: str
    start: int
    end: int


def _is_table_row(text: str) -> bool:
    return text.lstrip().startswith("|")


def split_sentences(text: str) -> list[Sentence]:
    """文単位に分割する。

    - 短い断片は次と結合して過分割を防ぐ(MIN_SENTENCE_CHARS)
    - 表 Markdown 行(`|` 始まり)は 1行 = 1単位。結合対象にしない(spec §3.1.2 手順2)
    """
    pieces: list[Sentence] = []
    cursor = 0
    for m in _BOUNDARY_RE.finditer(text):
        end = m.end()
        if end <= cursor:
            continue
        if _is_abbreviation_boundary(text, end):
            continue  # `e.g. Sleep` `Fig. 3` などを割らない
        pieces.append(Sentence(text=text[cursor:end], start=cursor, end=end))
        cursor = end
    if cursor < len(text):
        pieces.append(Sentence(text=text[cursor:], start=cursor, end=len(text)))

    merged: list[Sentence] = []
    for piece in pieces:
        prev = merged[-1] if merged else None
        can_merge = (
            prev is not None
            and len(prev.text.strip()) < MIN_SENTENCE_CHARS
            and not _is_table_row(prev.text)
            and not _is_table_row(piece.text)
        )
        if can_merge:
            merged.pop()
            merged.append(
                Sentence(text=text[prev.start : piece.end], start=prev.start, end=piece.end)
            )
        else:
            merged.append(piece)
    return [s for s in merged if s.text.strip()]


MULTILINGUAL_EMBEDDING_MODELS = frozenset(
    {"bge-m3", "bge-m3:latest", "multilingual-e5-large", "paraphrase-multilingual"}
)
# 相対判定: 最上位が2位より有意に離れているときだけ、その1文を採る。
# 「2位は1位と紛らわしいから信用しない」と「2位も返す」は両立しないため、
# 返すのは常に最大1件とする(spec §3.1.2 も1件に統一済み)。
MIN_MARGIN = 0.05
MIN_ABSOLUTE = 0.30
CJK_LANGUAGE_THRESHOLD = 0.3


class EmbedGateway(Protocol):
    async def embed(self, *, model: str, text: str) -> list[float]: ...


def is_cross_language(a: str, b: str) -> bool:
    """2つのテキストの主体言語が異なるか(CJK 比率で判定)。"""
    return (cjk_ratio(a) >= CJK_LANGUAGE_THRESHOLD) != (cjk_ratio(b) >= CJK_LANGUAGE_THRESHOLD)


def _is_multilingual(model: str) -> bool:
    base = model.split(":")[0]
    return model in MULTILINGUAL_EMBEDDING_MODELS or base in MULTILINGUAL_EMBEDDING_MODELS


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class SpanCache:
    """(chunk_id, sha1(claim), model) → spans の LRU キャッシュ。"""

    def __init__(self, limit: int = 256):
        self.limit = limit
        self._store: OrderedDict[tuple[str, str, str], list[dict[str, Any]]] = OrderedDict()

    def get(self, key: tuple[str, str, str]) -> list[dict[str, Any]] | None:
        if key not in self._store:
            return None
        self._store.move_to_end(key)
        # 実体を返すと、呼び出し側(ルータは answer_occurrence を差し替える)の
        # 書き換えがキャッシュを汚染する。複製を返す。
        return [dict(span) for span in self._store[key]]

    def put(self, key: tuple[str, str, str], value: list[dict[str, Any]]) -> None:
        self._store[key] = [dict(span) for span in value]
        self._store.move_to_end(key)
        while len(self._store) > self.limit:
            self._store.popitem(last=False)


async def score_spans(
    *,
    claim: str,
    chunk_text: str,
    chunk_id: str,
    gateway: EmbedGateway,
    model: str,
    cache: SpanCache,
) -> list[dict[str, Any]]:
    """主張文に意味的に近い文を最大1件返す。根拠の保証はない。"""
    if not claim.strip():
        # 空の主張文では類似度に意味が無い。埋め込みを呼ぶだけ無駄なので即座に諦める
        # (cjk_ratio('')=0 で言語跨ぎ判定にも掛からず、そのまま流れてしまっていた)。
        return []
    key = (chunk_id, hashlib.sha1(claim.encode("utf-8")).hexdigest(), model)
    cached = cache.get(key)
    if cached is not None:
        return cached

    if is_cross_language(claim, chunk_text) and not _is_multilingual(model):
        cache.put(key, [])
        return []

    sentences = split_sentences(chunk_text)
    if len(sentences) < 2:
        # 文が1つしかないチャンクでは「どこか」を絞れない(=チャンク全文になる)。
        # 全文ハイライトへの退化を防ぐため、ここで打ち切る。
        cache.put(key, [])
        return []

    claim_vec = await gateway.embed(model=model, text=claim)
    scored: list[tuple[float, Sentence]] = []
    for s in sentences:
        vec = await gateway.embed(model=model, text=s.text)
        scored.append((_cosine(claim_vec, vec), s))
    scored.sort(key=lambda p: p[0], reverse=True)

    top = scored[0][0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    if top < MIN_ABSOLUTE or (top - runner_up) < MIN_MARGIN:
        cache.put(key, [])
        return []

    best = scored[0][1]
    # 文分割は境界文字を次片の先頭に含めるため、先頭に空白や改行が残ることがある。
    # そのままだとハイライトが直前の行から始まって見えるので、両端を詰める。
    lead = len(best.text) - len(best.text.lstrip())
    trail = len(best.text) - len(best.text.rstrip())
    start = best.start + lead
    end = best.end - trail
    spans = [
        {
            "answer_occurrence": -1,  # 呼び出し側が実際の出現位置で上書きする
            "ordinal": None,
            "start": start,
            "end": end,
            "quote": chunk_text[start:end],
            "method": "embedding",
        }
    ]
    cache.put(key, spans)
    return spans

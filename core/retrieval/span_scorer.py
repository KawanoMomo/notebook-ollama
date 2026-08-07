"""根拠スパン解決 第2段 — 主張文⇔文の埋め込み類似(バッジ押下時のみ実行)。

設計: docs/specs/2026-08-07-citation-evidence-ui-design.md §3.1.2
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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

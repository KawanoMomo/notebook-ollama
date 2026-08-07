"""根拠スパン解決 第1段 — 生成後の字句照合(LLM 呼び出し・埋め込み計算なし)。

設計: docs/specs/2026-08-07-citation-evidence-ui-design.md §3.1.1
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_CITATION_RE = re.compile(r"\[\^(\d+)\]")
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
# markdown-it は 4スペース/タブ始まりの行もコードブロックにする。FE と計数の基準面を
# 揃えるため、BE 側でもこれをマスクする(揃えないと answer_occurrence が全域でズレる)。
_INDENT_CODE_RE = re.compile(r"(?m)^(?: {4}|\t).*$")
# 文末とみなす区切り。箇条書き先頭記号も文境界として扱う。
_SENTENCE_BOUNDARY_RE = re.compile(r"(?m)[。．!?！？\n]|^\s*[-*・]\s*")

# 主張文がこれより短ければ直前2文まで遡る。日本語の1文(「レベル2では成果物が
# 管理される」= 15文字)を安易に前文と繋げないため、20 ではなく 12 とする。
MIN_CLAIM_CHARS = 12


def mask_code_regions(text: str) -> str:
    """コード領域の中身を同じ長さの空白へ置換する。オフセットは保存される。"""

    def blank(m: re.Match[str]) -> str:
        return " " * len(m.group(0))

    masked = _FENCE_RE.sub(blank, text)
    masked = _INDENT_CODE_RE.sub(blank, masked)
    return _INLINE_CODE_RE.sub(blank, masked)


@dataclass(frozen=True)
class ClaimOccurrence:
    n: int
    answer_occurrence: int
    claim: str


def _claim_before(masked: str, marker_start: int) -> str:
    """marker_start の直前の1文を返す。短すぎる場合は直前2文まで遡る。"""
    head = masked[:marker_start]
    bounds = [m.end() for m in _SENTENCE_BOUNDARY_RE.finditer(head)]
    for take in (1, 2):
        start = bounds[-take] if len(bounds) >= take else 0
        claim = _CITATION_RE.sub("", head[start:]).strip()
        if len(claim) >= MIN_CLAIM_CHARS:
            return claim
    start = bounds[-2] if len(bounds) >= 2 else 0
    return _CITATION_RE.sub("", head[start:]).strip()


def iter_claim_occurrences(answer: str) -> list[ClaimOccurrence]:
    """回答中の [^n] を出現順に列挙し、各出現の主張文を切り出す。

    コード領域内のマーカーは数えない(BE/FE で計数の基準面を揃えるため)。
    """
    masked = mask_code_regions(answer)
    out: list[ClaimOccurrence] = []
    for occurrence, m in enumerate(_CITATION_RE.finditer(masked)):
        out.append(
            ClaimOccurrence(
                n=int(m.group(1)),
                answer_occurrence=occurrence,
                claim=_claim_before(masked, m.start()),
            )
        )
    return out


_PUNCT_CATEGORIES = {"Po", "Ps", "Pe", "Pi", "Pf", "Pd", "Pc"}


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x3040 <= code <= 0x30FF  # かな
        or 0x4E00 <= code <= 0x9FFF  # 漢字
        or 0x3400 <= code <= 0x4DBF
    )


def cjk_ratio(text: str) -> float:
    letters = [c for c in text if not c.isspace()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if _is_cjk(c)) / len(letters)


@dataclass(frozen=True)
class Normalized:
    text: str
    origin: list[int]


def normalize_for_match(text: str) -> Normalized:
    """NFKC → 小文字化 → 約物除去 → 空白の文字種別処理。逆写像を伴う。

    空白は「CJK どうしの間は除去、ラテンどうしの間は単一スペース」に畳む。
    英語の単語境界を壊すと頻出部分文字列で偽一致するため。
    """
    chars: list[str] = []
    origin: list[int] = []
    pending_space = False
    for idx, raw in enumerate(text):
        ch = unicodedata.normalize("NFKC", raw).lower()
        if not ch:
            continue
        ch = ch[0]
        if ch.isspace():
            pending_space = True
            continue
        if unicodedata.category(ch) in _PUNCT_CATEGORIES:
            continue
        if pending_space and chars:
            prev = chars[-1]
            if not _is_cjk(prev) and not _is_cjk(ch):
                chars.append(" ")
                origin.append(idx)
        pending_space = False
        chars.append(ch)
        origin.append(idx)
    return Normalized(text="".join(chars), origin=origin)

"""根拠スパン解決 第1段 — 生成後の字句照合(LLM 呼び出し・埋め込み計算なし)。

設計: docs/specs/2026-08-07-citation-evidence-ui-design.md §3.1.1
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

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


NGRAM = 6
CJK_MIN_COVERAGE = 0.30
CJK_MIN_RUN = 8
LATIN_MIN_COVERAGE = 0.40
LATIN_MIN_RUN = 15
CJK_MAIN_THRESHOLD = 0.3


def _match_positions(claim: str, chunk: str) -> list[tuple[int, int]]:
    """(claim 内の開始位置, chunk 内の開始位置) の一致 n-gram 一覧。"""
    pairs: list[tuple[int, int]] = []
    for ci in range(len(claim) - NGRAM + 1):
        gram = claim[ci : ci + NGRAM]
        pos = chunk.find(gram)
        while pos != -1:
            pairs.append((ci, pos))
            pos = chunk.find(gram, pos + 1)
    return pairs


def _best_window(pairs: list[tuple[int, int]], claim_len: int) -> list[tuple[int, int]]:
    """chunk 上で最も一致が密な窓を選び、その窓に入る組を返す。"""
    if not pairs:
        return []
    width = max(claim_len * 2, NGRAM * 4)
    ordered = sorted(pairs, key=lambda p: p[1])
    best: list[tuple[int, int]] = []
    left = 0
    for right in range(len(ordered)):
        while ordered[right][1] - ordered[left][1] > width:
            left += 1
        window = ordered[left : right + 1]
        if len({p[0] for p in window}) > len({p[0] for p in best}):
            best = window
    return best


def _longest_run(claim_positions: set[int]) -> int:
    """連続する claim 位置の最長連鎖を文字数に直す。"""
    if not claim_positions:
        return 0
    ordered = sorted(claim_positions)
    best = run = 1
    for prev, cur in zip(ordered, ordered[1:]):
        run = run + 1 if cur == prev + 1 else 1
        best = max(best, run)
    return best + NGRAM - 1


def resolve_lexical_span(claim: str, chunk_text: str) -> tuple[int, int] | None:
    """主張文の根拠スパンを chunk_text 上の (start, end) で返す。当たらなければ None。"""
    nc = normalize_for_match(claim)
    nt = normalize_for_match(chunk_text)
    if len(nc.text) < NGRAM or len(nt.text) < NGRAM:
        return None

    window = _best_window(_match_positions(nc.text, nt.text), len(nc.text))
    if not window:
        return None

    claim_positions = {p[0] for p in window}
    total = len(nc.text) - NGRAM + 1
    coverage = len(claim_positions) / total if total else 0.0
    run = _longest_run(claim_positions)

    if cjk_ratio(nc.text) >= CJK_MAIN_THRESHOLD:
        min_coverage, min_run = CJK_MIN_COVERAGE, CJK_MIN_RUN
    else:
        min_coverage, min_run = LATIN_MIN_COVERAGE, LATIN_MIN_RUN
    if coverage < min_coverage or run < min_run:
        return None

    lo = min(p[1] for p in window)
    hi = max(p[1] for p in window) + NGRAM - 1
    return nt.origin[lo], nt.origin[min(hi, len(nt.origin) - 1)] + 1


def attach_evidence_spans(
    *,
    answer: str,
    citations: list[dict[str, Any]],
    chunk_texts: dict[str, str],
) -> list[dict[str, Any]]:
    """各 citation に spans を付けた新しいリストを返す(引数は変更しない)。"""
    occurrences = iter_claim_occurrences(answer)
    spans_by_n: dict[int, list[dict[str, Any]]] = {}
    for occ in occurrences:
        citation = next((c for c in citations if c.get("n") == occ.n), None)
        if citation is None:
            continue
        text = chunk_texts.get(citation.get("chunk_id", ""))
        if not text:
            continue
        found = resolve_lexical_span(occ.claim, text)
        if found is None:
            continue
        start, end = found
        bucket = spans_by_n.setdefault(occ.n, [])
        bucket.append(
            {
                "answer_occurrence": occ.answer_occurrence,
                "ordinal": len(bucket) + 1,
                "start": start,
                "end": end,
                "quote": text[start:end],
                "method": "lexical",
            }
        )
    return [{**c, "spans": spans_by_n.get(c.get("n"), [])} for c in citations]

"""根拠スパン解決 第1段 — 生成後の字句照合(LLM 呼び出し・埋め込み計算なし)。

設計: docs/specs/2026-08-07-citation-evidence-ui-design.md §3.1.1
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any

_CITATION_RE = re.compile(r"\[\^(\d+)\]")
# 文末とみなす区切り。箇条書き先頭記号も文境界として扱う。
_SENTENCE_BOUNDARY_RE = re.compile(r"(?m)[。．!?！？\n]|^\s*[-*・]\s*")

# --- コード領域の判定 (CommonMark 準拠の部分集合) ---------------------------
#
# FE (markdown-it) と BE で「コード領域」の判定がズレると answer_occurrence が
# その後ろ全域でズレ、別の主張の根拠を自信満々に表示する誤帰属になる。素朴な
# 「4スペース始まりの行はコード」では次が全部ズレる:
#   - 入れ子箇条書き ("- a\n    - b") はコードではない
#   - 段落の遅延継続行 (空行なしの4スペース行) もコードではない
#     (インデントコードは段落を中断できない)
#   - 入れ子の番号付きリストも同様
# 逆に ``` だけを見ると ~~~ フェンス・未閉フェンス・改行をまたぐコードスパンを
# 取りこぼす。そこで行単位のブロック走査で CommonMark に寄せる。
# 検証は tests/unit/test_evidence_spans_code_regions.py と、対になる FE 側の
# apps/web/tests/unit/citationCodeRegions.test.ts (実際に markdown-it へ通す)。
_BLOCKQUOTE_PREFIX_RE = re.compile(r"^ {0,3}(?:> ?)+")
# 行頭空白を除いた本体に当てる。インデントの許容は桁数(indent - eff)で判定する。
_FENCE_BODY_RE = re.compile(r"^(`{3,}|~{3,})(.*)$")
_LIST_MARKER_RE = re.compile(r"^([-*+]|\d{1,9}[.)])([ \t]*)")
_ATX_HEADING_RE = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|$)")
_THEMATIC_BREAK_RE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
# 段落境界 (空行)。コードスパンはここを越えられない。
_PARA_BREAK_RE = re.compile(r"\n[ \t]*\n")
# インデントコードとみなす追加インデント幅。
_INDENT_CODE_WIDTH = 4

# 主張文がこれより短ければ直前2文まで遡る。日本語の1文(「レベル2では成果物が
# 管理される」= 15文字)を安易に前文と繋げないため、20 ではなく 12 とする。
MIN_CLAIM_CHARS = 12


def _indent_width(line: str) -> tuple[int, int]:
    """行頭の空白を桁数で数える。戻り値は (桁数, 先頭非空白の文字位置)。

    タブは CommonMark と同じく次の4桁境界まで進む。
    """
    col = 0
    idx = 0
    for ch in line:
        if ch == " ":
            col += 1
        elif ch == "\t":
            col += 4 - (col % 4)
        else:
            break
        idx += 1
    return col, idx


def _code_line_flags(lines: list[str]) -> list[bool]:
    """各行が「コードブロックの一部か」を返す(フェンス/インデントコード)。

    リストのネスト段数を content indent のスタックで持ち、「その時点の
    コンテナ基準で +4 桁以上」かつ「段落の途中でない」行だけをインデント
    コードとみなす。引用ブロックは先頭の `>` を剥がしてから同じ規則を当てる。
    """
    flags = [False] * len(lines)
    fence_char: str | None = None
    fence_len = 0
    # フェンスを開いた時点のリストコンテナ content indent。閉じフェンスの判定も
    # 同じ基準で行う(コンテナ相対で 0-3 桁のインデントは許される)。
    fence_container = 0
    in_indent_code = False
    in_paragraph = False
    list_indents: list[int] = []

    for i, raw in enumerate(lines):
        body = raw.rstrip("\r")
        quote = _BLOCKQUOTE_PREFIX_RE.match(body)
        if quote:
            body = body[quote.end() :]
        indent, marker_at = _indent_width(body)
        rest = body[marker_at:]
        is_blank = not rest.strip()

        if fence_char is not None:
            # 空行は「フェンスの内容」であってコンテナ継続の判定を受けない。
            # ここで閉じてしまうと、本来の閉じフェンスが新しい開きと誤認され、
            # 以降の本文までコード扱いになる(両方向のズレ)。
            if not is_blank and indent < fence_container:
                # コンテナより浅い行が来たらコンテナが閉じ、フェンスも閉じる。
                # この行自身が新しいフェンスの開きになりうるので、下の通常処理へ流す。
                fence_char = None
                fence_len = 0
                in_paragraph = False
                while list_indents and list_indents[-1] > indent:
                    list_indents.pop()
            else:
                flags[i] = True
                closing = _FENCE_BODY_RE.match(rest)
                if (
                    closing
                    and closing.group(1)[0] == fence_char
                    and len(closing.group(1)) >= fence_len
                    and indent - fence_container <= 3  # 相対4桁以上の ``` は閉じでなく内容
                    and not closing.group(2).strip()  # 閉じフェンスに info string は付かない
                ):
                    fence_char = None
                    fence_len = 0
                    in_paragraph = False
                continue

        # この行のインデントで実際に効いているコンテナ content indent。
        # スタックの top をそのまま使うと、リストを抜けた列0の行にまでネストの
        # インデントが適用され、フェンスを取り逃がす(= 直後のコードが本文として
        # 数えられ、さらに後続の本文がコード扱いになる両方向のズレ)。
        eff = 0
        for _v in list_indents:
            if _v <= indent:
                eff = _v
            else:
                break
        threshold = eff + _INDENT_CODE_WIDTH
        if in_indent_code:
            if is_blank or indent >= threshold:
                flags[i] = True
                continue
            in_indent_code = False

        if is_blank:
            in_paragraph = False
            continue

        # フェンスの許容インデントは「行頭から 0-3 桁」ではなく
        # 「効いているコンテナの content indent から 0-3 桁」。番号付きリスト
        # (content indent 3) 配下の4スペースフェンスは LLM 回答の頻出形状で、
        # 絶対桁で判定すると markdown-it と食い違う。
        # 桁数で比較する(文字数スライスにするとタブが1文字=4桁でズレる)。
        opening = _FENCE_BODY_RE.match(rest)
        if (
            opening
            and indent - eff <= 3
            and (opening.group(1)[0] == "~" or "`" not in opening.group(2))
        ):
            # フェンスは段落を中断できる。閉じられなければ文書末までコード。
            fence_char = opening.group(1)[0]
            fence_len = len(opening.group(1))
            fence_container = eff
            while list_indents and list_indents[-1] > eff:
                list_indents.pop()
            flags[i] = True
            in_paragraph = False
            continue

        if not in_paragraph and indent >= threshold:
            flags[i] = True
            in_indent_code = True
            continue

        is_break = bool(_THEMATIC_BREAK_RE.match(body))
        marker = None if is_break else _LIST_MARKER_RE.match(rest)
        if marker is not None:
            while list_indents and indent < list_indents[-1]:
                list_indents.pop()
            spaces = len(marker.group(2))
            # マーカー直後が行末、または空白5桁以上のときの content indent は +1。
            after = rest[marker.end() :]
            if not after.strip() or spaces == 0 or spaces > 4:
                spaces = 1
            list_indents.append(indent + len(marker.group(1)) + spaces)
            in_paragraph = True
            continue

        if not in_paragraph:
            # 空行を挟んで戻ってきた非インデント行はリストを閉じる
            # (段落の途中なら lazy continuation なので閉じない)。
            while list_indents and indent < list_indents[-1]:
                list_indents.pop()
        in_paragraph = not (is_break or _ATX_HEADING_RE.match(body))
    return flags


def _mask_block_code(text: str) -> str:
    lines = text.split("\n")
    flags = _code_line_flags(lines)
    out = [
        "".join(" " if ch != "\r" else ch for ch in line) if flag else line
        for line, flag in zip(lines, flags, strict=True)
    ]
    return "\n".join(out)


def _mask_inline_code(text: str) -> str:
    """コードスパンをマスクする。

    開始バッククォート列と「同じ長さ」の列で閉じる(CommonMark)。改行はまたげるが
    空行(段落境界)は越えられない。閉じられない列はただの文字として残す。
    """
    breaks = {m.start() for m in _PARA_BREAK_RE.finditer(text)}
    chars = list(text)
    n = len(chars)
    i = 0
    while i < n:
        if chars[i] != "`":
            i += 1
            continue
        j = i
        while j < n and chars[j] == "`":
            j += 1
        run = j - i
        k = j
        close = -1
        while k < n:
            if chars[k] == "`":
                m = k
                while m < n and chars[m] == "`":
                    m += 1
                if m - k == run:
                    close = k
                    break
                k = m
                continue
            if k in breaks:
                break
            k += 1
        if close < 0:
            i = j
            continue
        for p in range(i, close + run):
            if chars[p] not in ("\n", "\r"):
                chars[p] = " "
        i = close + run
    return "".join(chars)


def mask_code_regions(text: str) -> str:
    """コード領域の中身を同じ長さの空白へ置換する。オフセットは保存される。"""
    return _mask_inline_code(_mask_block_code(text))


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

# 最悪ケースの上限。PDF の表を抽出したチャンクは空白も句読点も無い日本語が延々と
# 続くことがあり、chunker が分割できずに数万文字の1チャンクになる。そこへ逐語で
# 引き写した回答が来ると一致ペアが百万単位になり、照合が秒単位〜分単位に膨れる。
# 呼び出し側 (stream.py / ask.py) はスレッドへ逃がすが、GIL を握る純 CPU なので
# 長時間の占有はイベントループの進行も鈍らせる。上限で最悪ケース自体を潰す。
# この機能は「当たらないなら黙る」方針なので、上限を超えたら偽陰性側に倒す。
MAX_CHUNK_CHARS = 20_000
MAX_MATCH_PAIRS = 50_000


def _match_positions(claim: str, chunk: str) -> list[tuple[int, int]] | None:
    """(claim 内の開始位置, chunk 内の開始位置) の一致 n-gram 一覧。

    MAX_MATCH_PAIRS を超えたら None を返す(=このチャンクでは特定を諦める)。
    """
    pairs: list[tuple[int, int]] = []
    for ci in range(len(claim) - NGRAM + 1):
        gram = claim[ci : ci + NGRAM]
        pos = chunk.find(gram)
        while pos != -1:
            pairs.append((ci, pos))
            if len(pairs) > MAX_MATCH_PAIRS:
                return None
            pos = chunk.find(gram, pos + 1)
    return pairs


def _best_window(pairs: list[tuple[int, int]], claim_len: int) -> list[tuple[int, int]]:
    """chunk 上で最も一致が密な窓を選び、その窓に入る組を返す。

    窓ごとにスライスと set を作り直すと O(ペア数 * 窓内ペア数) になり、反復の多い
    チャンクで二乗的に効く。claim 位置の出現数を Counter で増減させ、distinct 数を
    インクリメンタルに保つことで O(ペア数) にしてある。
    """
    if not pairs:
        return []
    width = max(claim_len * 2, NGRAM * 4)
    ordered = sorted(pairs, key=lambda p: p[1])
    counts: Counter[int] = Counter()
    distinct = 0
    best_distinct = 0
    best_left = 0
    best_right = -1
    left = 0
    for right, (claim_pos, _) in enumerate(ordered):
        if counts[claim_pos] == 0:
            distinct += 1
        counts[claim_pos] += 1
        while ordered[right][1] - ordered[left][1] > width:
            dropped = ordered[left][0]
            counts[dropped] -= 1
            if counts[dropped] == 0:
                distinct -= 1
            left += 1
        if distinct > best_distinct:
            best_distinct = distinct
            best_left, best_right = left, right
    return ordered[best_left : best_right + 1]


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
    if len(chunk_text) > MAX_CHUNK_CHARS:
        return None
    nc = normalize_for_match(claim)
    nt = normalize_for_match(chunk_text)
    if len(nc.text) < NGRAM or len(nt.text) < NGRAM:
        return None

    pairs = _match_positions(nc.text, nt.text)
    if pairs is None:  # 反復が多すぎる。偽陽性を出すより黙る。
        return None
    window = _best_window(pairs, len(nc.text))
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


# pixel-native の合成チャンク (core/retrieval/search.py の _pixel_native_chunk)。
# SQLite に実体行が無く、text は本文ではなく「添付画像を読み取って回答の根拠に
# してください」というプロンプト用のプレースホルダ。LLM がそれを引き写すと
# プレースホルダ上のオフセットでスパンが確定してしまうが、FE はこの prefix を見て
# 全文ビューへ落とすためチャンク本文を持たない = 無関係な位置を根拠として塗る。
# システム自身の指示文を「根拠」として提示しないよう、照合対象から外す。
_SYNTHETIC_CHUNK_ID_PREFIXES = ("vp:", "vt:")


def _is_synthetic_chunk(chunk_id: str) -> bool:
    return chunk_id.startswith(_SYNTHETIC_CHUNK_ID_PREFIXES)


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
        chunk_id = citation.get("chunk_id", "") or ""
        if _is_synthetic_chunk(chunk_id):
            continue
        text = chunk_texts.get(chunk_id)
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


def summarize_resolution(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = 0
    resolved = 0
    for rec in records:
        occurrences = iter_claim_occurrences(rec["answer"])
        total += len(occurrences)
        seen = {
            (c["n"], s["answer_occurrence"])
            for c in rec.get("citations", [])
            for s in c.get("spans", [])
        }
        resolved += sum(1 for o in occurrences if (o.n, o.answer_occurrence) in seen)
    rate = resolved / total if total else 0.0
    return {"total": total, "resolved": resolved, "rate": rate}

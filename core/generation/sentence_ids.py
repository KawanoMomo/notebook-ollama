"""β: 文ID方式の引用(LongCite 方式)。

設計: docs/specs/2026-08-07-citation-evidence-ui-design.md §3.6

事後の字句照合は「LLM が言い換えると当たらない」「言語跨ぎでは原理的に当たらない」
という限界を持つ。文ID方式は、プロンプト中の各文に通し番号 `<C1>` を振り、モデルには
その番号で引用させる。**文字列照合が不要になり、番号が正しければ位置は常に正確**。

対価は入力トークンの増加(1文あたり4〜6トークン)で、コンテキスト予算を圧迫する。
既定 OFF のベータとして現行方式と並置し、実測で比較するためのもの。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from core.retrieval.span_scorer import split_sentences

# 回答中の引用マーカー。`[^1:C12]` = 出典1の文C12。
_TAGGED_CITATION_RE = re.compile(r"\[\^(\d+):C(\d+)\]")
# 文ID を本文へ埋め込む書式。
_SENTENCE_TAG = "<C{sid}>"


@dataclass(frozen=True)
class SentenceRef:
    """文ID が指す実体。span の (start, end) はチャンク本文上のオフセット。"""

    sentence_id: int
    chunk_id: str
    start: int
    end: int
    text: str


def annotate_chunk_texts(
    chunks: list[tuple[str, str]],
) -> tuple[list[str], dict[int, SentenceRef]]:
    """(chunk_id, text) の列に文IDを振る。

    戻り値は (注釈付きテキストの列, 文ID→SentenceRef)。番号はチャンクを跨いで
    通しにする(チャンク内で振り直すと `C3` がどのチャンクか曖昧になるため)。
    """
    annotated: list[str] = []
    refs: dict[int, SentenceRef] = {}
    next_id = 1
    for chunk_id, text in chunks:
        parts: list[str] = []
        cursor = 0
        for sentence in split_sentences(text):
            # 文と文のあいだの空白などは、そのまま残して本文を壊さない。
            if sentence.start > cursor:
                parts.append(text[cursor : sentence.start])
            parts.append(_SENTENCE_TAG.format(sid=next_id))
            parts.append(sentence.text)
            refs[next_id] = SentenceRef(
                sentence_id=next_id,
                chunk_id=chunk_id,
                start=sentence.start,
                end=sentence.end,
                text=sentence.text,
            )
            next_id += 1
            cursor = sentence.end
        if cursor < len(text):
            parts.append(text[cursor:])
        annotated.append("".join(parts))
    return annotated, refs


def normalize_tagged_citations(answer: str) -> tuple[str, list[tuple[int, int, int]]]:
    """`[^n:Ck]` を `[^n]` に戻し、(出現順, n, 文ID) の列を返す。

    表示と既存パイプライン(build_citations / iter_claim_occurrences)は `[^n]` を
    前提にしているため、span を作る前にこの正規化を通す。
    """
    found: list[tuple[int, int, int]] = []
    occurrence = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal occurrence
        n = int(m.group(1))
        sid = int(m.group(2))
        found.append((occurrence, n, sid))
        occurrence += 1
        return f"[^{n}]"

    # 素の [^n] も出現番号を消費するので、両方を1回の走査で数える。
    pattern = re.compile(r"\[\^(\d+)(?::C(\d+))?\]")

    def repl_all(m: re.Match[str]) -> str:
        nonlocal occurrence
        n = int(m.group(1))
        sid = m.group(2)
        if sid is not None:
            found.append((occurrence, n, int(sid)))
        occurrence += 1
        return f"[^{n}]"

    del repl  # 単一走査版だけを使う
    return pattern.sub(repl_all, answer), found


def attach_sentence_id_spans(
    *,
    citations: list[dict[str, Any]],
    tagged: list[tuple[int, int, int]],
    refs: dict[int, SentenceRef],
) -> list[dict[str, Any]]:
    """文IDから spans を作る。番号が未知なら黙って捨てる(字句照合が拾う)。"""
    spans_by_n: dict[int, list[dict[str, Any]]] = {}
    for occurrence, n, sid in tagged:
        ref = refs.get(sid)
        if ref is None:
            continue  # モデルが番号を捏造した
        citation = next((c for c in citations if c.get("n") == n), None)
        if citation is None or citation.get("chunk_id") != ref.chunk_id:
            # 出典番号と文IDが噛み合っていない(別チャンクの文を指している)。
            # 誤った箇所を光らせないため採らない。
            continue
        bucket = spans_by_n.setdefault(n, [])
        bucket.append(
            {
                "answer_occurrence": occurrence,
                "ordinal": len(bucket) + 1,
                "start": ref.start,
                "end": ref.end,
                "quote": ref.text,
                "method": "sentence_id",
            }
        )
    return [{**c, "spans": spans_by_n.get(c.get("n"), [])} for c in citations]

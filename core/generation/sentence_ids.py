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

# 文ID を本文へ埋め込む書式。
_SENTENCE_TAG = "<C{sid}>"
# 範囲指定を展開する上限。これを超える範囲は端点2つだけを採る
# (モデルが C1-C999 のような無意味な範囲を出したときに全文が光るのを防ぐ)。
_MAX_RANGE_SPAN = 20


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


def normalize_tagged_citations(answer: str) -> tuple[str, list[tuple[int, int, tuple[int, ...]]]]:
    """`[^n:Ck]` を `[^n]` に戻し、(出現順, n, 引用された文IDの組) を返す。

    モデルは指示した `C12` の単独形だけでなく、`C15-C16` の範囲や `C15,C16` の
    列挙も出す(実機で観測)。範囲は端点間を展開し、列挙はそのまま保つ。
    **min〜max に潰さない**: `C15,C18` を潰すと、引用されていない C16/C17 まで
    根拠として光ってしまう。

    表示と既存パイプライン(build_citations / iter_claim_occurrences)は `[^n]` を
    前提にしているため、span を作る前にこの正規化を通す。
    """
    found: list[tuple[int, int, tuple[int, ...]]] = []
    occurrence = 0
    # 例: [^1] / [^1:C12] / [^1:C15-C16] / [^1:C15,C16] / [^1:C15, C16]
    pattern = re.compile(r"\[\^(\d+)((?::\s*C\d+(?:\s*[-,、]\s*C?\d+)*)?)\]")
    # 範囲かどうかは区切り文字で決まる。ハイフンは範囲、カンマ/読点は列挙。
    range_pair = re.compile(r"C?(\d+)\s*-\s*C?(\d+)")

    def repl(m: re.Match[str]) -> str:
        nonlocal occurrence
        n = int(m.group(1))
        tail = m.group(2) or ""
        ids: list[int] = []
        for part in re.split(r"[,、]", tail):
            hit = range_pair.search(part)
            if hit:
                lo, hi = int(hit.group(1)), int(hit.group(2))
                if lo <= hi and hi - lo <= _MAX_RANGE_SPAN:
                    ids.extend(range(lo, hi + 1))
                else:
                    ids.extend([lo, hi])
                continue
            ids.extend(int(x) for x in re.findall(r"\d+", part))
        if ids:
            # 重複を除きつつ出現順を保つ
            seen: dict[int, None] = {}
            for i in ids:
                seen.setdefault(i, None)
            found.append((occurrence, n, tuple(seen)))
        occurrence += 1
        return f"[^{n}]"

    return pattern.sub(repl, answer), found


def attach_sentence_id_spans(
    *,
    citations: list[dict[str, Any]],
    tagged: list[tuple[int, int, tuple[int, ...]]],
    refs: dict[int, SentenceRef],
) -> list[dict[str, Any]]:
    """文IDから spans を作る。

    引用された文それぞれが1つのスパンになる(範囲や列挙でも同じ)。1つのバッジ
    (= 回答中の1マーカー)に属するスパンは、同じ answer_occurrence と同じ枝番を
    共有する。噛み合わない文IDだけを個別に捨て、噛み合うものは残す。
    """
    spans_by_n: dict[int, list[dict[str, Any]]] = {}
    ordinal_by_n: dict[int, int] = {}
    for occurrence, n, ids in tagged:
        citation = next((c for c in citations if c.get("n") == n), None)
        if citation is None:
            continue
        chunk_id = citation.get("chunk_id")
        usable = [
            refs[i]
            for i in ids
            # 未知の番号(モデルの捏造)と、出典番号と噛み合わない文は採らない。
            # 誤った箇所を自信満々に光らせないため。
            if i in refs and refs[i].chunk_id == chunk_id
        ]
        if not usable:
            continue
        ordinal_by_n[n] = ordinal_by_n.get(n, 0) + 1
        ordinal = ordinal_by_n[n]
        bucket = spans_by_n.setdefault(n, [])
        for ref in sorted(usable, key=lambda r: r.start):
            bucket.append(
                {
                    "answer_occurrence": occurrence,
                    "ordinal": ordinal,
                    "start": ref.start,
                    "end": ref.end,
                    "quote": ref.text,
                    "method": "sentence_id",
                }
            )
    return [{**c, "spans": spans_by_n.get(c.get("n"), [])} for c in citations]

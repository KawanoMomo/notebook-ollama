"""回答が原文を引用符で丸ごと写している場合の解決。

言語跨ぎ(英語チャンクへの日本語回答)でも、引用符の中身は原文そのままなので
完全一致で位置を確定できる。実機で観測したパターン:

    説明: "Holds the data frame read from the receiver FIFO ..."(訳)
    この記載から、…であることが裏付けられています[^7]。
"""

from core.generation.evidence_spans import attach_evidence_spans

CHUNK = (
    "Table 23-19 SPI Registers. "
    "SCBx_RX_FIFO_RD: Holds the data frame read from the receiver FIFO. "
    "Reading a data frame removes the data frame from the FIFO."
)
CITATIONS = [{"n": 7, "chunk_id": "c1"}]
TEXTS = {"c1": CHUNK}


def test_japanese_claim_with_quoted_english_resolves():
    answer = (
        "説明: 「Holds the data frame read from the receiver FIFO.」"
        "この記載から、RX FIFO からデータを取得することが裏付けられています[^7]。"
    )
    got = attach_evidence_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    spans = got[0]["spans"]
    assert len(spans) == 1
    assert CHUNK[spans[0]["start"] : spans[0]["end"]] == (
        "Holds the data frame read from the receiver FIFO."
    )


def test_ascii_double_quotes_are_also_used():
    answer = (
        '説明は "Reading a data frame removes the data frame from the FIFO." です。'
        "したがって POP と同様の振る舞いになります[^7]。"
    )
    got = attach_evidence_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    assert len(got[0]["spans"]) == 1


def test_quote_not_in_chunk_is_ignored():
    answer = "説明は「This sentence does not exist in the chunk.」です[^7]。"
    got = attach_evidence_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    assert got[0]["spans"] == []


def test_short_quotes_are_ignored():
    """短い引用は偶然一致しやすいので使わない。"""
    answer = "「FIFO」について[^7]。"
    got = attach_evidence_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    assert got[0]["spans"] == []


def test_quote_from_previous_claim_does_not_leak():
    """引用は「直前のマーカー以降」に現れたものだけを使う。"""
    answer = (
        "説明は「Holds the data frame read from the receiver FIFO.」です[^7]。"
        "別の主張がここにある[^7]。"
    )
    got = attach_evidence_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    spans = got[0]["spans"]
    assert [s["answer_occurrence"] for s in spans] == [0]


def test_lexical_still_wins_when_no_quote():
    answer = "Reading a data frame removes the data frame from the FIFO[^7]。"
    got = attach_evidence_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    assert len(got[0]["spans"]) == 1

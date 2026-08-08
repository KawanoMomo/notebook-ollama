"""quote モードのスパンが第1段に上書きされないこと(出現単位のマージ)。"""

from core.generation.evidence_spans import attach_evidence_spans
from core.generation.quote_spans import attach_quote_spans

CHUNK = "レベル2では作業成果物が適切に管理される。監視及び調整、責任と権限の定義が求められる。"
CITATIONS = [{"n": 1, "chunk_id": "c1"}]
TEXTS = {"c1": CHUNK}


def test_quote_span_survives_lexical_pass():
    answer = "説明<q>レベル2では作業成果物が適切に管理される。</q>[^1]。"
    quoted = attach_quote_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    assert quoted[0]["spans"][0]["method"] == "quote"
    merged = attach_evidence_spans(answer=answer, citations=quoted, chunk_texts=TEXTS)
    assert merged[0]["spans"][0]["method"] == "quote", "第1段が quote スパンを上書きした"


def test_falls_back_to_lexical_when_quote_missing():
    answer = "レベル2では作業成果物が適切に管理される[^1]。"
    quoted = attach_quote_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    assert quoted[0]["spans"] == []
    merged = attach_evidence_spans(answer=answer, citations=quoted, chunk_texts=TEXTS)
    assert merged[0]["spans"][0]["method"] == "lexical"


def test_partial_quote_is_completed_by_lexical():
    """1つ目の出現だけ quote があり、2つ目は第1段が補う。"""
    answer = (
        "A<q>レベル2では作業成果物が適切に管理される。</q>[^1]。"
        "監視及び調整、責任と権限の定義が求められる[^1]。"
    )
    quoted = attach_quote_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    assert [s["method"] for s in quoted[0]["spans"]] == ["quote"]
    merged = attach_evidence_spans(answer=answer, citations=quoted, chunk_texts=TEXTS)
    methods = [s["method"] for s in merged[0]["spans"]]
    occurrences = [s["answer_occurrence"] for s in merged[0]["spans"]]
    assert methods == ["quote", "lexical"]
    assert occurrences == [0, 1]

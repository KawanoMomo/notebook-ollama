from core.generation.evidence_spans import attach_evidence_spans

CHUNK = (
    "プロセス能力レベル1は、実施されたプロセスの成果が達成されていることを示す。"
    "レベル2では作業成果物が適切に管理される。"
)
CITATIONS = [{"n": 3, "chunk_id": "c1"}]
TEXTS = {"c1": CHUNK}


def test_attaches_span_with_ordinal_and_occurrence():
    answer = "レベル2では作業成果物が適切に管理される[^3]。"
    got = attach_evidence_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    assert len(got[0]["spans"]) == 1
    span = got[0]["spans"][0]
    assert span["ordinal"] == 1
    assert span["answer_occurrence"] == 0
    assert span["method"] == "lexical"
    assert CHUNK[span["start"] : span["end"]] == span["quote"]


def test_two_occurrences_get_sequential_ordinals():
    answer = (
        "プロセス能力レベル1は実施されたプロセスの成果が達成されていることを示す[^3]。"
        "レベル2では作業成果物が適切に管理される[^3]。"
    )
    got = attach_evidence_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    spans = got[0]["spans"]
    assert [s["ordinal"] for s in spans] == [1, 2]
    assert [s["answer_occurrence"] for s in spans] == [0, 1]


def test_unresolved_occurrence_does_not_shift_ordinals():
    answer = (
        "段階が上がると管理の度合いが増していく仕組みである[^3]。"  # 未特定
        "レベル2では作業成果物が適切に管理される[^3]。"  # 特定できる
    )
    got = attach_evidence_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    spans = got[0]["spans"]
    assert len(spans) == 1
    assert spans[0]["answer_occurrence"] == 1  # 2番目の出現に正しく対応する
    assert spans[0]["ordinal"] == 1


def test_missing_chunk_text_yields_empty_spans():
    answer = "レベル2では作業成果物が適切に管理される[^3]。"
    got = attach_evidence_spans(answer=answer, citations=CITATIONS, chunk_texts={})
    assert got[0]["spans"] == []


def test_original_citations_are_not_mutated():
    answer = "レベル2では作業成果物が適切に管理される[^3]。"
    attach_evidence_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    assert "spans" not in CITATIONS[0]

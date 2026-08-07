from core.generation.evidence_spans import summarize_resolution as summarize


def test_summarize_counts_occurrences_not_citations():
    records = [
        {"answer": "A[^1]。B[^1]。", "citations": [{"n": 1, "spans": [{"answer_occurrence": 0}]}]},
    ]
    got = summarize(records)
    assert got["total"] == 2
    assert got["resolved"] == 1
    assert got["rate"] == 0.5


def test_summarize_handles_empty():
    assert summarize([]) == {"total": 0, "resolved": 0, "rate": 0.0}

from core.generation.quote_spans import attach_quote_spans, strip_quote_tags

CHUNK = "Level 1 indicates outcome achievement. Level 2 requires work product management."
CITATIONS = [{"n": 1, "chunk_id": "c1"}]
TEXTS = {"c1": CHUNK}


def test_strip_quote_tags_removes_markup_only():
    got = strip_quote_tags(
        "レベル2では管理される<q>Level 2 requires work product management.</q>[^1]。"
    )
    assert "<q>" not in got and "</q>" not in got
    assert "Level 2 requires work product management." in got


def test_attaches_span_from_quote():
    answer = "レベル2では管理される<q>Level 2 requires work product management.</q>[^1]。"
    got = attach_quote_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    spans = got[0]["spans"]
    assert len(spans) == 1
    assert spans[0]["method"] == "quote"
    assert spans[0]["ordinal"] == 1
    assert CHUNK[spans[0]["start"] : spans[0]["end"]] == "Level 2 requires work product management."


def test_quote_not_in_chunk_yields_no_span():
    answer = "でたらめ<q>This sentence is not in the chunk.</q>[^1]。"
    got = attach_quote_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    assert got[0]["spans"] == []


def test_multiple_quotes_get_sequential_ordinals():
    answer = (
        "A<q>Level 1 indicates outcome achievement.</q>[^1]。"
        "B<q>Level 2 requires work product management.</q>[^1]。"
    )
    got = attach_quote_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    spans = got[0]["spans"]
    assert [s["ordinal"] for s in spans] == [1, 2]
    assert [s["answer_occurrence"] for s in spans] == [0, 1]


def test_answer_without_quotes_is_unchanged():
    got = attach_quote_spans(answer="根拠なし[^1]。", citations=CITATIONS, chunk_texts=TEXTS)
    assert got[0]["spans"] == []


def test_quote_inside_code_block_is_ignored_for_counting():
    """コード領域内のマーカーは数えない(第1段と計数の基準面を揃える)。"""
    answer = (
        "本文<q>Level 1 indicates outcome achievement.</q>[^1]。\n"
        "```\n[^1]\n```\n"
    )
    got = attach_quote_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    assert len(got[0]["spans"]) == 1
    assert got[0]["spans"][0]["answer_occurrence"] == 0

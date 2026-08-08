"""モデルが出す実際の書式ゆれ(範囲・列挙)への耐性。

範囲や列挙は「引用された文それぞれ」を指す。min〜max に潰すと、列挙の
あいだにある引用されていない文まで巻き込んでしまう。
"""

from core.generation.sentence_ids import (
    annotate_chunk_texts,
    attach_sentence_id_spans,
    normalize_tagged_citations,
)

CHUNK = (
    "レベル1は成果の達成を示す。"
    "レベル2では作業成果物が管理される。"
    "監視及び調整が求められる。"
    "責任と権限の定義も必要である。"
)


def test_range_form_is_parsed_into_each_id():
    normalized, tagged = normalize_tagged_citations("説明[^1:C1-C2]。")
    assert normalized == "説明[^1]。"
    assert tagged == [(0, 1, (1, 2))]


def test_list_form_keeps_only_the_cited_ids():
    """C1,C4 は C2/C3 を含まない。"""
    normalized, tagged = normalize_tagged_citations("説明[^1:C1,C4]。")
    assert normalized == "説明[^1]。"
    assert tagged == [(0, 1, (1, 4))]


def test_single_form_still_works():
    _, tagged = normalize_tagged_citations("説明[^1:C2]。")
    assert tagged == [(0, 1, (2,))]


def test_each_cited_sentence_becomes_its_own_span():
    _, refs = annotate_chunk_texts([("c1", CHUNK)])
    citations = [{"n": 1, "chunk_id": "c1"}]
    got = attach_sentence_id_spans(citations=citations, tagged=[(0, 1, (1, 2))], refs=refs)
    spans = got[0]["spans"]
    assert len(spans) == 2
    assert CHUNK[spans[0]["start"] : spans[0]["end"]] == "レベル1は成果の達成を示す。"
    assert CHUNK[spans[1]["start"] : spans[1]["end"]] == "レベル2では作業成果物が管理される。"


def test_non_adjacent_list_does_not_swallow_the_middle():
    _, refs = annotate_chunk_texts([("c1", CHUNK)])
    citations = [{"n": 1, "chunk_id": "c1"}]
    got = attach_sentence_id_spans(citations=citations, tagged=[(0, 1, (1, 4))], refs=refs)
    texts = [CHUNK[s["start"] : s["end"]] for s in got[0]["spans"]]
    assert texts == ["レベル1は成果の達成を示す。", "責任と権限の定義も必要である。"]
    assert "監視及び調整" not in "".join(texts)


def test_spans_of_one_marker_share_occurrence_and_ordinal():
    """1つのバッジ = 1つの枝番。複数文でも番号は増えない。"""
    _, refs = annotate_chunk_texts([("c1", CHUNK)])
    citations = [{"n": 1, "chunk_id": "c1"}]
    got = attach_sentence_id_spans(
        citations=citations, tagged=[(0, 1, (1, 2)), (1, 1, (3,))], refs=refs
    )
    spans = got[0]["spans"]
    assert [s["answer_occurrence"] for s in spans] == [0, 0, 1]
    assert [s["ordinal"] for s in spans] == [1, 1, 2]


def test_ids_from_another_chunk_are_dropped_individually():
    """噛み合わない文だけを捨て、噛み合う文は残す。"""
    _, refs = annotate_chunk_texts([("c1", CHUNK), ("c2", "別チャンクの一文である。")])
    citations = [{"n": 1, "chunk_id": "c1"}]
    got = attach_sentence_id_spans(citations=citations, tagged=[(0, 1, (2, 5))], refs=refs)
    spans = got[0]["spans"]
    assert len(spans) == 1
    assert CHUNK[spans[0]["start"] : spans[0]["end"]] == "レベル2では作業成果物が管理される。"


def test_unknown_id_is_dropped():
    _, refs = annotate_chunk_texts([("c1", CHUNK)])
    citations = [{"n": 1, "chunk_id": "c1"}]
    got = attach_sentence_id_spans(citations=citations, tagged=[(0, 1, (999,))], refs=refs)
    assert got[0]["spans"] == []

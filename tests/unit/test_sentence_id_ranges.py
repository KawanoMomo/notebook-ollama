"""モデルが出す実際の書式ゆれ(範囲・列挙)への耐性。"""

from core.generation.sentence_ids import (
    annotate_chunk_texts,
    attach_sentence_id_spans,
    normalize_tagged_citations,
)

CHUNK = "レベル1は成果の達成を示す。レベル2では作業成果物が管理される。監視及び調整が求められる。"


def test_range_form_is_parsed():
    """[^1:C15-C16] のような範囲指定。実機で観測された書式。"""
    normalized, tagged = normalize_tagged_citations("説明[^1:C1-C2]。")
    assert normalized == "説明[^1]。"
    assert tagged == [(0, 1, 1, 2)]


def test_list_form_is_parsed():
    normalized, tagged = normalize_tagged_citations("説明[^1:C1,C3]。")
    assert normalized == "説明[^1]。"
    assert tagged == [(0, 1, 1, 3)]


def test_single_form_still_works():
    normalized, tagged = normalize_tagged_citations("説明[^1:C2]。")
    assert normalized == "説明[^1]。"
    assert tagged == [(0, 1, 2, 2)]


def test_range_span_covers_all_sentences():
    _, refs = annotate_chunk_texts([("c1", CHUNK)])
    citations = [{"n": 1, "chunk_id": "c1"}]
    got = attach_sentence_id_spans(citations=citations, tagged=[(0, 1, 1, 2)], refs=refs)
    span = got[0]["spans"][0]
    assert CHUNK[span["start"] : span["end"]] == "レベル1は成果の達成を示す。レベル2では作業成果物が管理される。"


def test_range_across_chunks_is_rejected():
    """範囲の両端が別チャンクにまたがるものは採らない。"""
    _, refs = annotate_chunk_texts([("c1", CHUNK), ("c2", "別チャンクの一文である。")])
    citations = [{"n": 1, "chunk_id": "c1"}]
    got = attach_sentence_id_spans(citations=citations, tagged=[(0, 1, 3, 4)], refs=refs)
    assert got[0]["spans"] == []


def test_unknown_id_in_range_is_dropped():
    _, refs = annotate_chunk_texts([("c1", CHUNK)])
    citations = [{"n": 1, "chunk_id": "c1"}]
    got = attach_sentence_id_spans(citations=citations, tagged=[(0, 1, 2, 999)], refs=refs)
    assert got[0]["spans"] == []

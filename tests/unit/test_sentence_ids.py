from core.generation.sentence_ids import (
    annotate_chunk_texts,
    attach_sentence_id_spans,
    normalize_tagged_citations,
)

CHUNK = "レベル1は成果の達成を示す。レベル2では作業成果物が管理される。監視及び調整が求められる。"


def test_annotate_adds_ids_and_keeps_text():
    annotated, refs = annotate_chunk_texts([("c1", CHUNK)])
    assert annotated[0].startswith("<C1>")
    assert "<C2>" in annotated[0]
    # タグを取り除くと元の本文に戻る
    import re

    assert re.sub(r"<C\d+>", "", annotated[0]) == CHUNK
    assert len(refs) == 3


def test_refs_point_at_the_original_offsets():
    _, refs = annotate_chunk_texts([("c1", CHUNK)])
    for ref in refs.values():
        assert CHUNK[ref.start : ref.end] == ref.text
        assert ref.chunk_id == "c1"


def test_ids_are_continuous_across_chunks():
    _, refs = annotate_chunk_texts([("c1", CHUNK), ("c2", "別のチャンクの一文目である。")])
    assert sorted(refs) == [1, 2, 3, 4]
    assert refs[4].chunk_id == "c2"


def test_normalize_rewrites_markers_and_records_ids():
    answer = "レベル2では管理される[^1:C2]。監視も要る[^1:C3]。"
    normalized, tagged = normalize_tagged_citations(answer)
    assert normalized == "レベル2では管理される[^1]。監視も要る[^1]。"
    assert tagged == [(0, 1, (2,)), (1, 1, (3,))]


def test_plain_markers_still_consume_occurrence_numbers():
    """素の [^n] が混じっても出現番号がズレない(モデルが書式を守り損ねた場合)。"""
    answer = "A[^1]。B[^1:C2]。"
    normalized, tagged = normalize_tagged_citations(answer)
    assert normalized == "A[^1]。B[^1]。"
    assert tagged == [(1, 1, (2,))]  # 2番目の出現だけ文IDを持つ


def test_attach_builds_spans_from_ids():
    _, refs = annotate_chunk_texts([("c1", CHUNK)])
    citations = [{"n": 1, "chunk_id": "c1"}]
    got = attach_sentence_id_spans(citations=citations, tagged=[(0, 1, (2,))], refs=refs)
    span = got[0]["spans"][0]
    assert span["method"] == "sentence_id"
    assert span["ordinal"] == 1
    # quote は呼び出し側(stream)がチャンク本文から切り出すので、位置で検証する
    assert CHUNK[span["start"] : span["end"]] == "レベル2では作業成果物が管理される。"


def test_unknown_sentence_id_is_dropped():
    _, refs = annotate_chunk_texts([("c1", CHUNK)])
    citations = [{"n": 1, "chunk_id": "c1"}]
    got = attach_sentence_id_spans(citations=citations, tagged=[(0, 1, (999,))], refs=refs)
    assert got[0]["spans"] == []


def test_id_from_another_chunk_is_rejected():
    """出典番号と文IDが噛み合わない場合は採らない(誤った箇所を光らせない)。"""
    _, refs = annotate_chunk_texts([("c1", CHUNK), ("c2", "別チャンクの一文である。")])
    citations = [{"n": 1, "chunk_id": "c1"}]
    got = attach_sentence_id_spans(citations=citations, tagged=[(0, 1, (4,))], refs=refs)
    assert got[0]["spans"] == []

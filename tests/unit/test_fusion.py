from core.retrieval.fusion import rrf_fuse
from core.retrieval.search import RetrievedChunk
from core.storage.visual_store import PageHit


def _chunk(cid, *, source_id="s1", page=1, score=0.9):
    return RetrievedChunk(
        chunk_id=cid, source_id=source_id, source_title="T", source_kind="pdf",
        page=page, heading_path=None, ord=0, text=f"text-{cid}",
        token_count=5, score=score,
    )


def test_rrf_scores_and_order():
    text = [_chunk("c1", page=1, score=0.9), _chunk("c2", page=2, score=0.5)]
    visual = [PageHit(source_id="s1", page=3, score=0.8)]
    result = rrf_fuse(text_hits=text, visual_hits=visual, k=60)
    # RRF: rank1 → 1/61, rank2 → 1/62
    assert result.ordered_text[0][0].chunk_id == "c1"
    assert abs(result.ordered_text[0][1] - 1 / 61) < 1e-9
    assert abs(result.ordered_text[1][1] - 1 / 62) < 1e-9
    assert result.surviving_pages[0][0].page == 3
    assert abs(result.surviving_pages[0][1] - 1 / 61) < 1e-9


def test_same_page_visual_hit_absorbed_by_text():
    """同一ページにテキスト・視覚両方でヒット → 視覚側を吸収(spec §6)。"""
    text = [_chunk("c1", source_id="s1", page=2)]
    visual = [PageHit(source_id="s1", page=2, score=0.8),
              PageHit(source_id="s1", page=9, score=0.7)]
    result = rrf_fuse(text_hits=text, visual_hits=visual)
    assert [p.page for p, _ in result.surviving_pages] == [9]


def test_absorption_matches_source_and_page_pair():
    """ページ番号が同じでも別ソースなら吸収しない。"""
    text = [_chunk("c1", source_id="s1", page=2)]
    visual = [PageHit(source_id="OTHER", page=2, score=0.8)]
    result = rrf_fuse(text_hits=text, visual_hits=visual)
    assert len(result.surviving_pages) == 1


def test_empty_inputs():
    result = rrf_fuse(text_hits=[], visual_hits=[])
    assert result.ordered_text == [] and result.surviving_pages == []

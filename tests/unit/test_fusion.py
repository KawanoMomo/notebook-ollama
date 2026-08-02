from core.retrieval.fusion import collapse_to_best_per_page, rrf_fuse
from core.retrieval.search import RetrievedChunk
from core.storage.visual_store import UnitHit


def _chunk(cid, *, source_id="s1", page=1, score=0.9):
    return RetrievedChunk(
        chunk_id=cid, source_id=source_id, source_title="T", source_kind="pdf",
        page=page, heading_path=None, ord=0, text=f"text-{cid}",
        token_count=5, score=score,
    )


def test_rrf_scores_and_order():
    text = [_chunk("c1", page=1, score=0.9), _chunk("c2", page=2, score=0.5)]
    visual = [UnitHit(source_id="s1", page=3, score=0.8)]
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
    visual = [UnitHit(source_id="s1", page=2, score=0.8),
              UnitHit(source_id="s1", page=9, score=0.7)]
    result = rrf_fuse(text_hits=text, visual_hits=visual)
    assert [p.page for p, _ in result.surviving_pages] == [9]


def test_absorption_matches_source_and_page_pair():
    """ページ番号が同じでも別ソースなら吸収しない。"""
    text = [_chunk("c1", source_id="s1", page=2)]
    visual = [UnitHit(source_id="OTHER", page=2, score=0.8)]
    result = rrf_fuse(text_hits=text, visual_hits=visual)
    assert len(result.surviving_pages) == 1


def test_empty_inputs():
    result = rrf_fuse(text_hits=[], visual_hits=[])
    assert result.ordered_text == [] and result.surviving_pages == []


def test_collapse_keeps_only_the_best_tile_per_page():
    """検索結果はスコア降順で来る。先頭が最上位タイル。"""
    hits = [
        UnitHit(source_id="s1", page=3, score=0.9, tile_index=1),
        UnitHit(source_id="s1", page=3, score=0.8, tile_index=0),   # 同じページ
        UnitHit(source_id="s1", page=7, score=0.7, tile_index=2),
        UnitHit(source_id="s2", page=3, score=0.6, tile_index=0),   # 別ソースの同じページ番号
        UnitHit(source_id="s1", page=3, score=0.5, tile_index=2),   # 同じページ
    ]
    out = collapse_to_best_per_page(hits)
    assert [(h.source_id, h.page, h.tile_index) for h in out] == [
        ("s1", 3, 1),
        ("s1", 7, 2),
        ("s2", 3, 0),
    ]


def test_collapse_is_identity_for_page_unit_hits():
    hits = [
        UnitHit(source_id="s1", page=1, score=0.9),
        UnitHit(source_id="s1", page=2, score=0.8),
    ]
    assert collapse_to_best_per_page(hits) == hits


def test_collapse_handles_empty():
    assert collapse_to_best_per_page([]) == []


def test_rrf_absorption_uses_page_not_tile():
    """テキストが p.3 に当たっていれば、p.3 のどのタイルも吸収される。"""
    text = [_chunk("c1", source_id="s1", page=3)]
    visual = [
        UnitHit(source_id="s1", page=3, score=0.9, tile_index=1),
        UnitHit(source_id="s1", page=5, score=0.8, tile_index=0),
    ]
    result = rrf_fuse(text_hits=text, visual_hits=visual)
    assert [h.page for h, _ in result.surviving_pages] == [5]


def test_rrf_preserves_tile_index_on_surviving_pages():
    visual = [UnitHit(source_id="s1", page=5, score=0.8, tile_index=2)]
    result = rrf_fuse(text_hits=[], visual_hits=visual)
    assert result.surviving_pages[0][0].tile_index == 2

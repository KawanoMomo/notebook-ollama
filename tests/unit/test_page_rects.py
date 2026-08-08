import json

import pymupdf

from core.sources.page_rects import Rect, rects_from_asset_bbox, rects_from_quote


def test_asset_bbox_is_scaled_from_points_to_pixels():
    bbox = json.dumps([72.0, 144.0, 144.0, 216.0])  # 1inch,2inch → 2inch,3inch
    got = rects_from_asset_bbox(bbox, dpi=150)
    assert len(got) == 1
    assert got[0] == Rect(x=150.0, y=300.0, w=150.0, h=150.0)


def test_asset_bbox_none_returns_empty():
    assert rects_from_asset_bbox(None, dpi=150) == []


def test_asset_bbox_broken_json_returns_empty():
    assert rects_from_asset_bbox("not json", dpi=150) == []


def _make_pdf(path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(
        pymupdf.Rect(50, 100, 500, 200),
        "The process achieves its outcomes.",
        fontsize=12,
        fontname="helv",
    )
    doc.save(path)
    doc.close()


def test_quote_search_finds_rect(tmp_path):
    pdf = tmp_path / "s.pdf"
    _make_pdf(pdf)
    got = rects_from_quote(pdf, page=1, quote="achieves its outcomes", dpi=150)
    assert len(got) >= 1
    assert got[0].w > 0 and got[0].h > 0


def test_quote_not_found_returns_empty(tmp_path):
    pdf = tmp_path / "s.pdf"
    _make_pdf(pdf)
    assert rects_from_quote(pdf, page=1, quote="no such sentence here", dpi=150) == []


def test_quote_falls_back_to_word_pieces(tmp_path):
    """行末ハイフネーション等で全体一致しない場合、単語単位の部分一致で拾う。"""
    pdf = tmp_path / "s.pdf"
    _make_pdf(pdf)
    got = rects_from_quote(pdf, page=1, quote="The process ZZZ achieves its outcomes", dpi=150)
    assert len(got) >= 1


def test_out_of_range_page_returns_empty(tmp_path):
    pdf = tmp_path / "s.pdf"
    _make_pdf(pdf)
    assert rects_from_quote(pdf, page=99, quote="achieves", dpi=150) == []

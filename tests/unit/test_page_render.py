import pymupdf
import pytest

from core.sources.page_render import (
    ALLOWED_DPI,
    UnsupportedDpiError,
    cache_path_for,
    purge_source_cache,
    render_page_png,
)


def _make_pdf(path, pages=2):
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 500, 200), f"page {i + 1}", fontsize=14)
    doc.save(path)
    doc.close()


def test_renders_png_bytes(tmp_path):
    pdf = tmp_path / "s.pdf"
    _make_pdf(pdf)
    out = render_page_png(pdf_path=pdf, page=1, dpi=150, cache_dir=tmp_path / "cache")
    assert out.startswith(b"\x89PNG")


def test_second_call_hits_cache(tmp_path):
    pdf = tmp_path / "s.pdf"
    _make_pdf(pdf)
    cache = tmp_path / "cache"
    first = render_page_png(pdf_path=pdf, page=1, dpi=150, cache_dir=cache)
    cached_file = next(cache.rglob("*.png"))
    cached_file.write_bytes(b"\x89PNG-sentinel")
    second = render_page_png(pdf_path=pdf, page=1, dpi=150, cache_dir=cache)
    assert second == b"\x89PNG-sentinel"
    assert first != second


def test_rejects_dpi_outside_allowlist(tmp_path):
    pdf = tmp_path / "s.pdf"
    _make_pdf(pdf)
    with pytest.raises(UnsupportedDpiError):
        render_page_png(pdf_path=pdf, page=1, dpi=1200, cache_dir=tmp_path / "cache")
    assert ALLOWED_DPI == frozenset({150, 300})


def test_rejects_out_of_range_page(tmp_path):
    pdf = tmp_path / "s.pdf"
    _make_pdf(pdf, pages=2)
    with pytest.raises(IndexError):
        render_page_png(pdf_path=pdf, page=3, dpi=150, cache_dir=tmp_path / "cache")


def test_purge_removes_only_that_source(tmp_path):
    cache = tmp_path / "cache"
    a = cache_path_for(cache, "src-a", 1, 150)
    b = cache_path_for(cache, "src-b", 1, 150)
    for p in (a, b):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    purge_source_cache(cache, "src-a")
    assert not a.exists()
    assert b.exists()

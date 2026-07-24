import pytest

pymupdf = pytest.importorskip("pymupdf")
pytestmark = pytest.mark.pdf

from core.ingestion.parsers.pdf import PdfParser  # noqa: E402
from tests.unit.fixtures_pdf import build_pdf_with_image  # noqa: E402


async def test_figure_cropped_as_png_asset():
    doc = await PdfParser().parse_bytes(build_pdf_with_image(), extract_assets=True)
    figs = [a for a in doc.assets if a.kind == "figure"]
    assert len(figs) == 1
    assert figs[0].image_png[:8] == b"\x89PNG\r\n\x1a\n"
    assert figs[0].page == 1


async def test_tiny_image_excluded():
    doc = await PdfParser().parse_bytes(
        build_pdf_with_image(img_size=(10, 10)), extract_assets=True
    )
    assert [a for a in doc.assets if a.kind == "figure"] == []

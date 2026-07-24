from __future__ import annotations

import pytest

pymupdf = pytest.importorskip("pymupdf")
pytestmark = pytest.mark.pdf

import pymupdf as _pymupdf  # noqa: E402

from core.ingestion.parsers.pdf import PdfParser  # noqa: E402


class FakeOcrEngine:
    def __init__(self, text: str | None):
        self._text = text
        self.calls = 0

    async def ocr_page(self, *, image_png: bytes) -> str | None:
        self.calls += 1
        return self._text


def _scanned_pdf_bytes() -> bytes:
    """テキストレイヤーを一切持たない(画像のみの)PDFを合成する。"""
    doc = _pymupdf.open()
    page = doc.new_page(width=595, height=842)
    pm = _pymupdf.Pixmap(_pymupdf.csRGB, _pymupdf.IRect(0, 0, 400, 500), False)
    pm.set_rect(pm.irect, (255, 255, 255))
    page.insert_image(_pymupdf.Rect(0, 0, 595, 842), pixmap=pm)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.mark.asyncio
async def test_scanned_pdf_uses_ocr_when_engine_provided():
    engine = FakeOcrEngine("OCRで読み取った本文です。")
    doc = await PdfParser().parse_bytes(
        _scanned_pdf_bytes(), source_hint="scan.pdf", ocr_engine=engine
    )
    assert engine.calls == 1
    assert len(doc.sections) == 1
    assert doc.sections[0].text == "OCRで読み取った本文です。"


@pytest.mark.asyncio
async def test_scanned_pdf_without_ocr_engine_raises_as_before():
    from core.exceptions import AppError

    with pytest.raises(AppError, match="no extractable text"):
        await PdfParser().parse_bytes(_scanned_pdf_bytes(), source_hint="scan.pdf")


@pytest.mark.asyncio
async def test_scanned_pdf_ocr_all_pages_fail_raises():
    engine = FakeOcrEngine(None)
    from core.exceptions import AppError

    with pytest.raises(AppError):
        await PdfParser().parse_bytes(
            _scanned_pdf_bytes(), source_hint="scan.pdf", ocr_engine=engine
        )

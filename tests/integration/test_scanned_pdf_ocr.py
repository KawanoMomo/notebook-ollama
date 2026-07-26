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
async def test_scanned_pdf_without_ocr_engine_raises_japanese_with_remediation():
    """実機FB 2026-07-26: 日本語アプリなのに英語メッセージが出ていた。
    メッセージは日本語、かつ「次に何をすればよいか」を remediation で示すこと。"""
    from core.exceptions import AppError

    with pytest.raises(AppError) as excinfo:
        await PdfParser().parse_bytes(_scanned_pdf_bytes(), source_hint="scan.pdf")
    assert "テキストが含まれていません" in excinfo.value.message
    assert "OCR" in (excinfo.value.remediation or "")


@pytest.mark.asyncio
async def test_disabled_ocr_engine_reports_no_text_not_ocr_failure():
    """実機FB 2026-07-26: アプリは常に LazyOcrEngine を渡すため、ベータOFFでも
    OCR経路に入り「OCRでも読み取れませんでした」と表示されていた。実際には
    一度もOCRしていないので、テキスト無しとして報告すること。"""
    from core.exceptions import AppError

    class DisabledEngine:
        def is_available(self) -> bool:
            return False

        async def ocr_page(self, *, image_png: bytes) -> str | None:
            raise AssertionError("無効なエンジンは呼ばれてはならない")

    with pytest.raises(AppError) as excinfo:
        await PdfParser().parse_bytes(
            _scanned_pdf_bytes(), source_hint="scan.pdf", ocr_engine=DisabledEngine()
        )
    assert "テキストが含まれていません" in excinfo.value.message
    assert "読み取れませんでした" not in excinfo.value.message


@pytest.mark.asyncio
async def test_scanned_pdf_ocr_all_pages_fail_raises_with_actionable_remediation():
    """OCR も失敗した場合、「視覚モデルの設定を確認」は行き止まりだった
    (設定済みで、問題は小型VLMの能力)。外部OCRという実際に前へ進める
    手段を案内すること。"""
    engine = FakeOcrEngine(None)
    from core.exceptions import AppError

    with pytest.raises(AppError) as excinfo:
        await PdfParser().parse_bytes(
            _scanned_pdf_bytes(), source_hint="scan.pdf", ocr_engine=engine
        )
    assert "読み取れませんでした" in excinfo.value.message
    remediation = excinfo.value.remediation or ""
    assert "OCR" in remediation
    assert "設定を確認" not in remediation

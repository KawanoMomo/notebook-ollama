import pytest

from core.ingestion.ocr_engine import OllamaOcrEngine


class FakeGateway:
    def __init__(self, text: str):
        self._text = text

    async def chat_stream(self, *, model, messages, options=None, meta=None):
        for ch in self._text:
            yield ch
        if meta is not None:
            meta["done_reason"] = "stop"


@pytest.mark.asyncio
async def test_ocr_page_returns_transcribed_text():
    engine = OllamaOcrEngine(
        client=FakeGateway("これはOCRされたページ本文です。"), model="qwen3-vl"
    )
    result = await engine.ocr_page(image_png=b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)
    assert result == "これはOCRされたページ本文です。"


@pytest.mark.asyncio
async def test_ocr_page_returns_none_on_empty():
    engine = OllamaOcrEngine(client=FakeGateway(""), model="qwen3-vl")
    result = await engine.ocr_page(image_png=b"\x89PNG\r\n\x1a\n")
    assert result is None

import pytest

from core.ingestion.ocr_engine import LazyOcrEngine, OllamaOcrEngine


class FakeGateway:
    def __init__(self, text: str):
        self._text = text
        self.calls: list[dict] = []

    async def chat_stream(self, *, model, messages, options=None, meta=None):
        self.calls.append({"model": model, "messages": messages})
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


@pytest.mark.asyncio
async def test_lazy_ocr_engine_uses_current_model_each_call():
    """model_getter を呼び出しの都度評価する(起動後の Settings 変更に追従)。"""
    gw = FakeGateway("書き起こしたテキスト")
    model_box = {"value": "llava:7b"}
    engine = LazyOcrEngine(client=gw, model_getter=lambda: model_box["value"])

    await engine.ocr_page(image_png=b"\x89PNG\r\n\x1a\n")
    model_box["value"] = "qwen3-vl"
    await engine.ocr_page(image_png=b"\x89PNG\r\n\x1a\n")

    assert gw.calls[0]["model"] == "llava:7b"
    assert gw.calls[1]["model"] == "qwen3-vl"


@pytest.mark.asyncio
async def test_lazy_ocr_engine_returns_none_when_model_unset():
    gw = FakeGateway("呼ばれないはず")
    engine = LazyOcrEngine(client=gw, model_getter=lambda: "")
    result = await engine.ocr_page(image_png=b"\x89PNG\r\n\x1a\n")
    assert result is None
    assert gw.calls == []


@pytest.mark.asyncio
async def test_lazy_ocr_engine_returns_none_when_disabled():
    gw = FakeGateway("呼ばれないはず")
    engine = LazyOcrEngine(
        client=gw, model_getter=lambda: "llava:7b", enabled_getter=lambda: False
    )
    result = await engine.ocr_page(image_png=b"\x89PNG\r\n\x1a\n")
    assert result is None
    assert gw.calls == []

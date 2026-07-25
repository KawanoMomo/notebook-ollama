import base64

import pytest

from core.ingestion.figure_describer import LazyFigureDescriber, OllamaFigureDescriber

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20


class FakeThinkingGatewayLike:
    """chat_stream 相当の fake。responses はラウンドごとの (tokens) タプル列。"""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def chat_stream(self, *, model, messages, options=None, meta=None):
        self.calls.append({"model": model, "messages": messages})
        text = self.responses.pop(0)
        for ch in text:
            yield ch
        if meta is not None:
            meta["done_reason"] = "stop"


@pytest.mark.asyncio
async def test_describe_returns_text_on_success():
    gw = FakeThinkingGatewayLike(["これは部品配置図です。ネジとナットが描かれています。"])
    describer = OllamaFigureDescriber(client=gw, model="qwen3-vl")
    result = await describer.describe(image_png=PNG_BYTES)
    assert result == "これは部品配置図です。ネジとナットが描かれています。"
    # 画像は base64 化されて messages に images キーで乗る
    sent = gw.calls[0]["messages"][-1]
    assert "images" in sent
    assert sent["images"][0] == base64.b64encode(PNG_BYTES).decode("ascii")


@pytest.mark.asyncio
async def test_describe_retries_once_on_empty_response():
    gw = FakeThinkingGatewayLike(["", "リトライで成功しました。"])
    describer = OllamaFigureDescriber(client=gw, model="qwen3-vl")
    result = await describer.describe(image_png=PNG_BYTES)
    assert result == "リトライで成功しました。"
    assert len(gw.calls) == 2


@pytest.mark.asyncio
async def test_describe_returns_none_after_retry_still_empty():
    gw = FakeThinkingGatewayLike(["", "  "])
    describer = OllamaFigureDescriber(client=gw, model="qwen3-vl")
    result = await describer.describe(image_png=PNG_BYTES)
    assert result is None
    assert len(gw.calls) == 2


@pytest.mark.asyncio
async def test_describe_returns_none_on_exception():
    class BoomGateway:
        async def chat_stream(self, *, model, messages, options=None, meta=None):
            raise RuntimeError("ollama down")
            yield  # pragma: no cover

    describer = OllamaFigureDescriber(client=BoomGateway(), model="qwen3-vl")
    result = await describer.describe(image_png=PNG_BYTES)
    assert result is None


@pytest.mark.asyncio
async def test_lazy_describer_uses_current_model_each_call():
    """model_getter を呼び出しの都度評価する(起動後の Settings 変更に追従)。"""
    gw = FakeThinkingGatewayLike(["最初のモデルで説明。", "変更後のモデルで説明。"])
    model_box = {"value": "llava:7b"}
    describer = LazyFigureDescriber(client=gw, model_getter=lambda: model_box["value"])

    first = await describer.describe(image_png=PNG_BYTES)
    model_box["value"] = "qwen3-vl"
    second = await describer.describe(image_png=PNG_BYTES)

    assert first == "最初のモデルで説明。"
    assert second == "変更後のモデルで説明。"
    assert gw.calls[0]["model"] == "llava:7b"
    assert gw.calls[1]["model"] == "qwen3-vl"


@pytest.mark.asyncio
async def test_lazy_describer_returns_none_when_model_unset():
    gw = FakeThinkingGatewayLike(["呼ばれないはず"])
    describer = LazyFigureDescriber(client=gw, model_getter=lambda: "")
    result = await describer.describe(image_png=PNG_BYTES)
    assert result is None
    assert gw.calls == []


@pytest.mark.asyncio
async def test_lazy_describer_returns_none_when_disabled():
    gw = FakeThinkingGatewayLike(["呼ばれないはず"])
    describer = LazyFigureDescriber(
        client=gw, model_getter=lambda: "llava:7b", enabled_getter=lambda: False
    )
    result = await describer.describe(image_png=PNG_BYTES)
    assert result is None
    assert gw.calls == []

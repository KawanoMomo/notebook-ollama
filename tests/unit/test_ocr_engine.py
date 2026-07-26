import pytest

from core.ingestion.ocr_engine import LazyOcrEngine, OllamaOcrEngine


class FakeGateway:
    def __init__(self, text: str):
        self._text = text
        self.calls: list[dict] = []

    async def chat_stream(self, *, model, messages, options=None, meta=None):
        self.calls.append({"model": model, "messages": messages, "options": options})
        for ch in self._text:
            yield ch
        if meta is not None:
            meta["done_reason"] = "stop"


class FakeSequenceGateway:
    """chat_stream 相当の fake。responses はラウンドごとの応答テキスト列。"""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def chat_stream(self, *, model, messages, options=None, meta=None):
        self.calls.append({"model": model, "messages": messages, "options": options})
        text = self.responses.pop(0)
        for ch in text:
            yield ch
        if meta is not None:
            meta["done_reason"] = "stop"


@pytest.mark.asyncio
async def test_ocr_page_excludes_thinking_tokens():
    """実機FB 2026-07-27: 視覚モデルを thinking 系にすると、
    「Thinking Process: ...」「Wait, looking closely at ...」が
    ページ本文として索引に入っていた。ThinkingChunk は除外すること。"""
    from core.ollama.client import ThinkingChunk

    class ThinkingGateway:
        def __init__(self):
            self.calls = []

        async def chat_stream(self, *, model, messages, options=None, meta=None):
            self.calls.append({"model": model, "options": options})
            yield ThinkingChunk("Thinking Process: 1. Analyze the Request. ")
            yield "本日の給食献立表です。カレーライスと牛乳。"

    engine = OllamaOcrEngine(client=ThinkingGateway(), model="aratan/Agents-A1-4B")
    result = await engine.ocr_page(image_png=b"\x89PNG\r\n\x1a\n")
    assert result == "本日の給食献立表です。カレーライスと牛乳。"
    assert "Thinking Process" not in (result or "")


@pytest.mark.asyncio
async def test_ocr_page_caps_generation_length():
    """無制限だと thinking 系モデルの出力が埋め込み上限を超える
    (実機FB 2026-07-27)。num_predict を必ず指定する。"""
    gw = FakeGateway("これはOCRされたページ本文です。")
    engine = OllamaOcrEngine(client=gw, model="qwen3-vl")
    await engine.ocr_page(image_png=b"\x89PNG\r\n\x1a\n")
    options = gw.calls[0]["options"] or {}
    assert options.get("num_predict", 0) > 0


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
async def test_ocr_page_rejects_refusal_response():
    """小型VLM(実機: llava:7b)は書き起こしを拒否することがある。拒否文を
    そのまま採用すると非空なので成功扱いになり、RAG索引を汚染してしまう
    (evaluator実機確認: 拒否文がそのまま ready 化していた)。"""
    gw = FakeSequenceGateway([
        "申し訳、スキャン文書のページを提供することができません。",
        "申し訳、スキャン文書のページを提供することができません。",
    ])
    engine = OllamaOcrEngine(client=gw, model="llava:7b")
    result = await engine.ocr_page(image_png=b"\x89PNG\r\n\x1a\n")
    assert result is None
    assert len(gw.calls) == 2  # 1回リトライしてから諦める


@pytest.mark.asyncio
async def test_ocr_page_rejects_too_short_response():
    gw = FakeSequenceGateway(["短い", "短い"])
    engine = OllamaOcrEngine(client=gw, model="llava:7b")
    result = await engine.ocr_page(image_png=b"\x89PNG\r\n\x1a\n")
    assert result is None


@pytest.mark.asyncio
async def test_ocr_page_retries_once_on_refusal_then_succeeds():
    gw = FakeSequenceGateway([
        "申し訳ございませんが、書き起こしできません。",
        "会議録\n出席者: 田中、鈴木\n議題: 予算について",
    ])
    engine = OllamaOcrEngine(client=gw, model="llava:7b")
    result = await engine.ocr_page(image_png=b"\x89PNG\r\n\x1a\n")
    assert result == "会議録\n出席者: 田中、鈴木\n議題: 予算について"
    assert len(gw.calls) == 2


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

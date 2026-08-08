import pytest

from core.translation.translator import (
    MAX_TRANSLATE_CHARS,
    TextTooLongError,
    build_messages,
    translate_stream,
)


class FakeGateway:
    def __init__(self):
        self.calls: list[dict] = []

    async def chat_stream(self, *, model, messages, options=None, meta=None):
        self.calls.append({"model": model, "messages": messages})
        for tok in ["これは", "訳文", "です"]:
            yield tok


def test_build_messages_states_target_language():
    msgs = build_messages("Hello world", "ja")
    assert msgs[0]["role"] == "system"
    assert "日本語" in msgs[0]["content"]
    assert msgs[-1]["content"].endswith("Hello world")


def test_build_messages_forbids_commentary():
    joined = " ".join(m["content"] for m in build_messages("Hello", "ja"))
    assert "訳文のみ" in joined


@pytest.mark.asyncio
async def test_translate_stream_yields_tokens():
    gw = FakeGateway()
    out = [t async for t in translate_stream(text="Hello", target_lang="ja", model="m", gateway=gw)]
    assert "".join(out) == "これは訳文です"
    assert gw.calls[0]["model"] == "m"


@pytest.mark.asyncio
async def test_empty_text_yields_nothing_and_calls_nothing():
    gw = FakeGateway()
    out = [t async for t in translate_stream(text="   ", target_lang="ja", model="m", gateway=gw)]
    assert out == []
    assert gw.calls == []


@pytest.mark.asyncio
async def test_too_long_text_is_rejected():
    gw = FakeGateway()
    with pytest.raises(TextTooLongError):
        [
            t
            async for t in translate_stream(
                text="x" * (MAX_TRANSLATE_CHARS + 1), target_lang="ja", model="m", gateway=gw
            )
        ]

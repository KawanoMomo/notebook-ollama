import asyncio

from core.ollama.gateway import OllamaGateway


class _FakeClient:
    def __init__(self) -> None:
        self.chat_calls: list[tuple[str, list[dict], dict | None]] = []

    async def chat_stream(self, *, model, messages, options=None):
        await asyncio.sleep(0)
        self.chat_calls.append((model, list(messages), options))
        for tok in ["Hel", "lo", " world"]:
            yield tok


def test_generate_accumulates_stream_into_string():
    client = _FakeClient()
    gw = OllamaGateway(client=client)
    out = asyncio.run(gw.generate(model="m", prompt="hi", options={"temperature": 0}))
    assert out == "Hello world"


def test_generate_passes_prompt_as_user_message_and_options():
    client = _FakeClient()
    gw = OllamaGateway(client=client)
    asyncio.run(gw.generate(model="qwen", prompt="P", options={"temperature": 0}))
    assert len(client.chat_calls) == 1
    model, messages, options = client.chat_calls[0]
    assert model == "qwen"
    assert messages == [{"role": "user", "content": "P"}]
    assert options == {"temperature": 0}

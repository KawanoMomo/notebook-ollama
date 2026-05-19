import asyncio
import pytest
from core.ollama.gateway import OllamaGateway

class FakeClient:
    def __init__(self):
        self.embed_calls: list[tuple[str, str]] = []
        self.chat_calls: list[tuple[str, list[dict]]] = []

    async def embed(self, *, model: str, text: str) -> list[float]:
        await asyncio.sleep(0.01)
        self.embed_calls.append((model, text))
        return [0.0, 1.0]

    async def chat_stream(self, *, model, messages, options=None):
        await asyncio.sleep(0.01)
        self.chat_calls.append((model, list(messages)))
        for tok in ["a", "b"]:
            yield tok

@pytest.mark.asyncio
async def test_gateway_embeds_concurrently_serialized():
    client = FakeClient()
    gw = OllamaGateway(client=client)
    await asyncio.gather(*(gw.embed(model="m", text=f"t{i}") for i in range(5)))
    assert len(client.embed_calls) == 5

@pytest.mark.asyncio
async def test_chat_serialized_by_fifo():
    client = FakeClient()
    gw = OllamaGateway(client=client)

    started: list[int] = []

    async def run(i):
        async for tok in gw.chat_stream(model="m", messages=[{"role": "user", "content": str(i)}]):
            started.append(i)
            return  # stop after first token

    await asyncio.gather(*(run(i) for i in range(3)))
    # FIFO: tasks resolve in dispatch order
    assert started == sorted(started)

@pytest.mark.asyncio
async def test_chat_and_embed_use_separate_queues():
    client = FakeClient()
    gw = OllamaGateway(client=client)
    await asyncio.gather(
        gw.embed(model="m", text="x"),
        anext(gw.chat_stream(model="m", messages=[{"role": "user", "content": "y"}])),
    )
    assert client.embed_calls and client.chat_calls

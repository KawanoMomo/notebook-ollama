import httpx
import pytest
import respx

from core.exceptions import AppError, ErrorCode
from core.ollama.client import OllamaClient


@pytest.mark.asyncio
async def test_embed_returns_vector():
    with respx.mock(assert_all_called=True) as router:
        router.post("http://fake/api/embeddings").mock(
            return_value=httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})
        )
        client = OllamaClient(endpoint="http://fake")
        v = await client.embed(model="bge-m3", text="hello")
        assert v == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_chat_stream_yields_tokens():
    payloads = [
        b'{"message":{"content":"Hello"},"done":false}\n',
        b'{"message":{"content":" world"},"done":false}\n',
        b'{"message":{"content":""},"done":true}\n',
    ]
    with respx.mock() as router:
        router.post("http://fake/api/chat").mock(
            return_value=httpx.Response(200, content=b"".join(payloads))
        )
        client = OllamaClient(endpoint="http://fake")
        tokens: list[str] = []
        async for tok in client.chat_stream(
            model="qwen2.5:14b",
            messages=[{"role": "user", "content": "hi"}],
            options={"num_ctx": 4096},
        ):
            tokens.append(tok)
        assert "".join(tokens) == "Hello world"


@pytest.mark.asyncio
async def test_list_models_returns_tags():
    with respx.mock() as router:
        router.get("http://fake/api/tags").mock(
            return_value=httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "qwen2.5:14b", "size": 1, "modified_at": "2026-05-01T00:00:00Z"},
                    ]
                },
            )
        )
        client = OllamaClient(endpoint="http://fake")
        tags = await client.list_tags()
        assert tags[0]["name"] == "qwen2.5:14b"


@pytest.mark.asyncio
async def test_show_returns_parameters():
    with respx.mock() as router:
        router.post("http://fake/api/show").mock(
            return_value=httpx.Response(
                200,
                json={
                    "parameters": 'stop "</s>"\nnum_ctx 32768',
                    "details": {"parameter_size": "14B", "family": "qwen"},
                },
            )
        )
        client = OllamaClient(endpoint="http://fake")
        info = await client.show("qwen2.5:14b")
        assert info["details"]["family"] == "qwen"


@pytest.mark.asyncio
async def test_chat_stream_read_timeout_raises_app_error():
    with respx.mock() as router:
        router.post("http://fake/api/chat").mock(side_effect=httpx.ReadTimeout("read timed out"))
        client = OllamaClient(endpoint="http://fake", chat_read_timeout=1.0)
        with pytest.raises(AppError) as ei:
            async for _ in client.chat_stream(
                model="qwen2.5:14b",
                messages=[{"role": "user", "content": "hi"}],
            ):
                pass
        assert ei.value.code == ErrorCode.OLLAMA_UNREACHABLE

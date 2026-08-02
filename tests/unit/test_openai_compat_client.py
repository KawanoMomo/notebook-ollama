"""``OpenAICompatClient`` — OpenAI互換サーバー向け ``_ClientLike`` 実装の単体テスト。

spec addendum "Update 2026-08-02" §L(Phase 1.5)。``OllamaClient`` の既存
テスト(``test_ollama_client_done_reason.py``)と同じ httpx.AsyncClient
monkeypatch パターンで、HTTP 層をフェイクして契約を検証する。
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from core.exceptions import AppError, ErrorCode
from core.ollama import openai_compat as compat_mod
from core.ollama.client import ThinkingChunk
from core.ollama.openai_compat import (
    OpenAICompatClient,
    _map_options,
    _to_openai_messages,
)

# ---------------------------------------------------------------------------
# fakes (httpx.AsyncClient 差し替え)
# ---------------------------------------------------------------------------


class _FakeStreamResponse:
    def __init__(self, lines: list[str], status_code: int = 200):
        self._lines = lines
        self.status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):
        return b"boom"


class _FakePostResponse:
    def __init__(self, payload: Any, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """post(embed) と stream(chat) の両方を受けるフェイク。

    受け取った URL / json / headers を ``calls`` に記録し、テストが
    リクエスト形状をアサートできるようにする。
    """

    calls: list[dict[str, Any]] = []
    post_response: _FakePostResponse | None = None
    stream_lines: list[str] = []
    stream_status: int = 200

    def __init__(self, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        type(self).calls.append(
            {"method": "POST", "url": url, "json": json, "headers": headers}
        )
        assert type(self).post_response is not None
        return type(self).post_response

    def stream(self, method, url, json=None, headers=None):
        type(self).calls.append(
            {"method": method, "url": url, "json": json, "headers": headers}
        )
        return _FakeStreamResponse(
            type(self).stream_lines, status_code=type(self).stream_status
        )


@pytest.fixture()
def fake_client(monkeypatch) -> type[_FakeAsyncClient]:
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.post_response = None
    _FakeAsyncClient.stream_lines = []
    _FakeAsyncClient.stream_status = 200
    monkeypatch.setattr(compat_mod.httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}"


# ---------------------------------------------------------------------------
# embed
# ---------------------------------------------------------------------------


async def test_embed_posts_v1_embeddings_and_returns_vector(fake_client):
    fake_client.post_response = _FakePostResponse(
        {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
    )
    c = OpenAICompatClient(endpoint="http://fake:8080")
    vec = await c.embed(model="bge-m3", text="hello")
    assert vec == [0.1, 0.2, 0.3]
    call = fake_client.calls[0]
    assert call["url"] == "http://fake:8080/v1/embeddings"
    assert call["json"] == {"model": "bge-m3", "input": "hello"}


async def test_embed_ignores_ollama_options(fake_client):
    """num_gpu=0 等の Ollama 固有 option は openai-compat 経路では送らない。"""
    fake_client.post_response = _FakePostResponse(
        {"data": [{"embedding": [1.0]}]}
    )
    c = OpenAICompatClient(endpoint="http://fake:8080")
    await c.embed(model="m", text="t", options={"num_gpu": 0})
    assert "options" not in fake_client.calls[0]["json"]
    assert "num_gpu" not in json.dumps(fake_client.calls[0]["json"])


async def test_embed_404_maps_to_model_not_found(fake_client):
    fake_client.post_response = _FakePostResponse({"error": "no"}, status_code=404)
    c = OpenAICompatClient(endpoint="http://fake:8080")
    with pytest.raises(AppError) as ei:
        await c.embed(model="missing", text="t")
    assert ei.value.code == ErrorCode.OLLAMA_MODEL_NOT_FOUND


async def test_embed_500_maps_to_generation_failed(fake_client):
    fake_client.post_response = _FakePostResponse({"error": "x"}, status_code=500)
    c = OpenAICompatClient(endpoint="http://fake:8080")
    with pytest.raises(AppError) as ei:
        await c.embed(model="m", text="t")
    assert ei.value.code == ErrorCode.OLLAMA_GENERATION_FAILED


async def test_embed_malformed_response_maps_to_generation_failed(fake_client):
    fake_client.post_response = _FakePostResponse({"unexpected": True})
    c = OpenAICompatClient(endpoint="http://fake:8080")
    with pytest.raises(AppError) as ei:
        await c.embed(model="m", text="t")
    assert ei.value.code == ErrorCode.OLLAMA_GENERATION_FAILED


# ---------------------------------------------------------------------------
# chat_stream
# ---------------------------------------------------------------------------


async def test_chat_stream_yields_content_and_done_reason(fake_client):
    fake_client.stream_lines = [
        _sse({"choices": [{"delta": {"content": "こん"}}]}),
        _sse({"choices": [{"delta": {"content": "にちは"}}]}),
        _sse({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
        "data: [DONE]",
    ]
    c = OpenAICompatClient(endpoint="http://fake:8080")
    meta: dict = {}
    toks = [t async for t in c.chat_stream(model="m", messages=[], meta=meta)]
    assert toks == ["こん", "にちは"]
    assert meta["done_reason"] == "stop"
    call = fake_client.calls[0]
    assert call["url"] == "http://fake:8080/v1/chat/completions"
    assert call["json"]["stream"] is True


async def test_chat_stream_exposes_done_reason_length(fake_client):
    """finish_reason=length は Ollama done_reason と同語彙で meta に入る
    (自動継続 issue #22 の打ち切り検知が openai-compat でも機能する)。"""
    fake_client.stream_lines = [
        _sse({"choices": [{"delta": {"content": "abc"}}]}),
        _sse({"choices": [{"delta": {}, "finish_reason": "length"}]}),
        "data: [DONE]",
    ]
    c = OpenAICompatClient(endpoint="http://fake:8080")
    meta: dict = {}
    _ = [t async for t in c.chat_stream(model="m", messages=[], meta=meta)]
    assert meta["done_reason"] == "length"


async def test_chat_stream_yields_reasoning_as_thinking_chunk(fake_client):
    fake_client.stream_lines = [
        _sse({"choices": [{"delta": {"reasoning_content": "うーん"}}]}),
        _sse({"choices": [{"delta": {"content": "答え"}}]}),
        _sse({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
        "data: [DONE]",
    ]
    c = OpenAICompatClient(endpoint="http://fake:8080")
    toks = [t async for t in c.chat_stream(model="m", messages=[])]
    assert toks == ["うーん", "答え"]
    assert isinstance(toks[0], ThinkingChunk)
    assert not isinstance(toks[1], ThinkingChunk)


async def test_chat_stream_maps_options_to_openai_params(fake_client):
    fake_client.stream_lines = ["data: [DONE]"]
    c = OpenAICompatClient(endpoint="http://fake:8080")
    _ = [
        t
        async for t in c.chat_stream(
            model="m",
            messages=[],
            options={"num_predict": 512, "temperature": 0.2, "num_ctx": 8192},
        )
    ]
    sent = fake_client.calls[0]["json"]
    assert sent["max_tokens"] == 512
    assert sent["temperature"] == 0.2
    # num_ctx は対応概念なし — ペイロードに漏れない
    assert "num_ctx" not in sent
    assert "options" not in sent


async def test_chat_stream_http_error_maps_to_unreachable(fake_client, monkeypatch):
    import httpx as real_httpx

    class _RaisingClient(_FakeAsyncClient):
        def stream(self, method, url, json=None, headers=None):
            raise real_httpx.ConnectError("refused")

    monkeypatch.setattr(compat_mod.httpx, "AsyncClient", _RaisingClient)
    c = OpenAICompatClient(endpoint="http://fake:8080")
    with pytest.raises(AppError) as ei:
        _ = [t async for t in c.chat_stream(model="m", messages=[])]
    assert ei.value.code == ErrorCode.OLLAMA_UNREACHABLE


async def test_chat_stream_4xx_maps_to_generation_failed(fake_client):
    fake_client.stream_status = 400
    fake_client.stream_lines = []
    c = OpenAICompatClient(endpoint="http://fake:8080")
    with pytest.raises(AppError) as ei:
        _ = [t async for t in c.chat_stream(model="m", messages=[])]
    assert ei.value.code == ErrorCode.OLLAMA_GENERATION_FAILED


# ---------------------------------------------------------------------------
# api key / endpoint 正規化 / メッセージ変換
# ---------------------------------------------------------------------------


async def test_api_key_sent_as_bearer_only_when_set(fake_client):
    fake_client.post_response = _FakePostResponse(
        {"data": [{"embedding": [1.0]}]}
    )
    c = OpenAICompatClient(endpoint="http://fake:8080", api_key="sk-x")
    await c.embed(model="m", text="t")
    assert fake_client.calls[0]["headers"] == {"Authorization": "Bearer sk-x"}

    fake_client.calls = []
    c2 = OpenAICompatClient(endpoint="http://fake:8080")
    await c2.embed(model="m", text="t")
    assert fake_client.calls[0]["headers"] == {}


def test_endpoint_v1_suffix_not_doubled():
    c = OpenAICompatClient(endpoint="http://fake:8080/v1/")
    assert c._endpoint == "http://fake:8080"


def test_map_options_drops_unknown_and_maps_known():
    params, dropped = _map_options(
        {"num_predict": 128, "top_p": 0.9, "num_gpu": 0, "repeat_penalty": 1.1}
    )
    assert params == {"max_tokens": 128, "top_p": 0.9}
    assert sorted(dropped) == ["num_gpu", "repeat_penalty"]


def test_map_options_unlimited_num_predict_omits_max_tokens():
    params, _ = _map_options({"num_predict": -1})
    assert "max_tokens" not in params


def test_to_openai_messages_passthrough_text_only():
    msgs = [{"role": "user", "content": "hi"}]
    assert _to_openai_messages(msgs) == [{"role": "user", "content": "hi"}]


def test_to_openai_messages_converts_ollama_images():
    msgs = [{"role": "user", "content": "この図を説明して", "images": ["QUJD"]}]
    out = _to_openai_messages(msgs)
    assert out[0]["role"] == "user"
    parts = out[0]["content"]
    assert parts[0] == {"type": "text", "text": "この図を説明して"}
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"] == "data:image/png;base64,QUJD"

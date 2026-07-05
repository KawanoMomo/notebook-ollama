"""OllamaClient.chat_stream が最終チャンクの done_reason を meta へ公開する。

num_predict 上限による打ち切り(done_reason="length")を上位層が検知できる
ようにする(2026-07-05 実機FB: チャット回答が無言で途中終了)。
"""
from __future__ import annotations

import json

import pytest

from core.ollama import client as client_mod
from core.ollama.client import OllamaClient


class _FakeResponse:
    def __init__(self, lines: list[str]):
        self._lines = lines
        self.status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):
        return b""


class _FakeAsyncClient:
    def __init__(self, lines: list[str]):
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url, json=None):
        return _FakeResponse(self._lines)


def _install_fake(monkeypatch, lines: list[str]) -> None:
    monkeypatch.setattr(
        client_mod.httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(lines)
    )


@pytest.mark.asyncio
async def test_chat_stream_exposes_done_reason_length(monkeypatch):
    lines = [
        json.dumps({"message": {"content": "abc"}, "done": False}),
        json.dumps({"message": {"content": ""}, "done": True, "done_reason": "length"}),
    ]
    _install_fake(monkeypatch, lines)
    c = OllamaClient(endpoint="http://fake")
    meta: dict = {}
    toks = [t async for t in c.chat_stream(model="m", messages=[], meta=meta)]
    assert toks == ["abc"]
    assert meta["done_reason"] == "length"


@pytest.mark.asyncio
async def test_chat_stream_exposes_done_reason_stop(monkeypatch):
    lines = [
        json.dumps({"message": {"content": "abc"}, "done": False}),
        json.dumps({"message": {"content": ""}, "done": True, "done_reason": "stop"}),
    ]
    _install_fake(monkeypatch, lines)
    c = OllamaClient(endpoint="http://fake")
    meta: dict = {}
    _ = [t async for t in c.chat_stream(model="m", messages=[], meta=meta)]
    assert meta["done_reason"] == "stop"


@pytest.mark.asyncio
async def test_chat_stream_without_meta_still_streams(monkeypatch):
    lines = [
        json.dumps({"message": {"content": "abc"}, "done": False}),
        json.dumps({"done": True, "done_reason": "stop"}),
    ]
    _install_fake(monkeypatch, lines)
    c = OllamaClient(endpoint="http://fake")
    toks = [t async for t in c.chat_stream(model="m", messages=[])]
    assert toks == ["abc"]


@pytest.mark.asyncio
async def test_chat_stream_yields_thinking_chunks_typed(monkeypatch):
    """message.thinking は ThinkingChunk 型で yield され、content と区別できる。"""
    from core.ollama.client import ThinkingChunk

    lines = [
        json.dumps({"message": {"thinking": "うーん"}, "done": False}),
        json.dumps({"message": {"thinking": "考え中"}, "done": False}),
        json.dumps({"message": {"content": "答え"}, "done": False}),
        json.dumps({"done": True, "done_reason": "stop"}),
    ]
    _install_fake(monkeypatch, lines)
    c = OllamaClient(endpoint="http://fake")
    toks = [t async for t in c.chat_stream(model="m", messages=[])]
    assert toks == ["うーん", "考え中", "答え"]
    assert isinstance(toks[0], ThinkingChunk)
    assert isinstance(toks[1], ThinkingChunk)
    assert not isinstance(toks[2], ThinkingChunk)

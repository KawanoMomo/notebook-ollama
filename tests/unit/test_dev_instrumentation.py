"""OllamaClient 計装と OllamaServerLogTail のテスト(spec §8.2 / §8.4)。"""
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest

from core.dev_logs.broker import DevBroker
from core.dev_logs.ring import DevLogRing
from core.dev_logs import ring as ring_mod
from core.dev_logs.tail import OllamaServerLogTail
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


@pytest.fixture
def dev_ring(monkeypatch):
    """計装点が参照する singleton ring を、テスト専用の新品に差し替える。"""
    fresh = DevLogRing()
    fresh.enable(capacity_bytes=1024 * 1024)
    monkeypatch.setattr(ring_mod, "ring", fresh)
    yield fresh


@pytest.mark.asyncio
async def test_chat_stream_emits_req_chunk_resp(monkeypatch, dev_ring):
    lines = [
        json.dumps({"message": {"content": "ab"}, "done": False}),
        json.dumps({"message": {"content": "cd"}, "done": False}),
        json.dumps({"done": True, "done_reason": "stop", "eval_count": 4}),
    ]
    monkeypatch.setattr(
        client_mod.httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(lines)
    )
    c = OllamaClient(endpoint="http://fake")
    _ = [t async for t in c.chat_stream(model="m", messages=[{"role": "user", "content": "q"}])]

    entries = dev_ring.read(limit=100).entries
    phases = [e["payload"].get("phase") for e in entries if e["source"] == "ollama"]
    assert phases == ["req", "chunk", "chunk", "resp"]
    resp = entries[-1]["payload"]
    assert resp["done_reason"] == "stop"
    assert resp["chunks"] == 2
    assert resp["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_chat_stream_error_emits_error_phase(monkeypatch, dev_ring):
    class _BoomClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, *a, **kw):
            raise httpx.ConnectError("boom")

    monkeypatch.setattr(client_mod.httpx, "AsyncClient", lambda **kw: _BoomClient())
    c = OllamaClient(endpoint="http://fake")
    from core.exceptions import AppError

    with pytest.raises(AppError):
        _ = [t async for t in c.chat_stream(model="m", messages=[])]

    entries = dev_ring.read(limit=100).entries
    phases = [e["payload"].get("phase") for e in entries if e["source"] == "ollama"]
    assert phases == ["req", "error"]


def _wait_for(cond, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_tail_streams_appended_lines(tmp_path):
    ring = DevLogRing()
    ring.enable(capacity_bytes=1024 * 1024)
    log = tmp_path / "server.log"
    log.write_text("old line\n", encoding="utf-8")
    tail = OllamaServerLogTail(ring=ring, broker=DevBroker(), path=log)
    tail.start()
    try:
        with log.open("a", encoding="utf-8") as f:
            f.write("new line 1\nnew line 2\n")
        assert _wait_for(lambda: ring.stats["entries"] >= 2)
        msgs = [e["msg"] for e in ring.read(limit=100).entries]
        assert "new line 1" in msgs and "new line 2" in msgs
        assert "old line" not in msgs  # 末尾から追従(既存分は読まない)
    finally:
        tail.stop()


def test_tail_missing_file_pushes_single_warn(tmp_path):
    ring = DevLogRing()
    ring.enable(capacity_bytes=1024 * 1024)
    tail = OllamaServerLogTail(
        ring=ring, broker=DevBroker(), path=tmp_path / "does-not-exist.log"
    )
    tail.start()
    assert _wait_for(lambda: ring.stats["entries"] >= 1)
    time.sleep(0.2)
    entries = ring.read(limit=100).entries
    assert len(entries) == 1
    assert entries[0]["level"] == "warn"
    assert "not found" in entries[0]["msg"]
    tail.stop()

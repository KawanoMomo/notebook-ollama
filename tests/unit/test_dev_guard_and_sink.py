"""開発者モードのガード / シンク / ブローカのユニットテスト(仕様 §5.2, §8.1, §7.5)。"""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from core.dev_logs.broker import DevBroker
from core.dev_logs.ring import DevLogRing
from core.dev_logs.sink import DevSinkHandler, make_dev_structlog_processor
from core.exceptions import AppError


def _request(host: str | None, *, enabled: bool, headers: dict | None = None):
    cfg = SimpleNamespace(dev=SimpleNamespace(enabled=enabled))
    ctx = SimpleNamespace(config=cfg)
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(ctx=ctx)),
        client=SimpleNamespace(host=host) if host is not None else None,
        headers=headers or {},
    )


# ---------------------------------------------------------------------------
# guard_dev_request (§5.2)
# ---------------------------------------------------------------------------


def test_guard_403_when_disabled():
    from apps.api.routers.dev import guard_dev_request

    with pytest.raises(AppError) as ei:
        guard_dev_request(_request("127.0.0.1", enabled=False))
    assert ei.value.code.value == "dev.unauthorized"


def test_guard_403_for_lan_ip():
    from apps.api.routers.dev import guard_dev_request

    with pytest.raises(AppError):
        guard_dev_request(_request("192.168.1.23", enabled=True))


def test_guard_passes_for_localhost_when_enabled():
    from apps.api.routers.dev import guard_dev_request

    guard_dev_request(_request("127.0.0.1", enabled=True))
    guard_dev_request(_request("::1", enabled=True))


def test_guard_ignores_x_forwarded_for():
    from apps.api.routers.dev import guard_dev_request

    # XFF が localhost を主張しても client.host が LAN なら 403(NFR-3)
    req = _request(
        "192.168.1.23", enabled=True, headers={"x-forwarded-for": "127.0.0.1"}
    )
    with pytest.raises(AppError):
        guard_dev_request(req)


# ---------------------------------------------------------------------------
# DevSinkHandler (§8.1)
# ---------------------------------------------------------------------------


def _fresh_ring(enabled: bool = True) -> DevLogRing:
    r = DevLogRing()
    if enabled:
        r.enable(capacity_bytes=1024 * 1024)
    return r


def test_sink_skips_when_ring_disabled():
    ring = _fresh_ring(enabled=False)
    h = DevSinkHandler(ring=ring, broker=None)
    rec = logging.LogRecord("x", logging.INFO, "f.py", 1, "hello", None, None)
    h.emit(rec)
    assert ring.stats["entries"] == 0


def test_sink_captures_stdlib_record():
    ring = _fresh_ring()
    h = DevSinkHandler(ring=ring, broker=None)
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "f.py", 1, "GET /api", None, None)
    h.emit(rec)
    res = ring.read()
    assert len(res.entries) == 1
    e = res.entries[0]
    assert e["source"] == "app"
    assert e["msg"] == "GET /api"
    assert e["payload"]["logger"] == "uvicorn.access"


def test_sink_ignores_own_dev_logs_logger():
    ring = _fresh_ring()
    h = DevSinkHandler(ring=ring, broker=None)
    rec = logging.LogRecord("dev_logs", logging.WARNING, "f.py", 1, "boom", None, None)
    h.emit(rec)
    assert ring.stats["entries"] == 0


def test_structlog_processor_preserves_keys_and_passes_through():
    ring = _fresh_ring()
    proc = make_dev_structlog_processor(ring=ring, broker=None)
    event_dict = {"event": "summary_complete", "source_id": "s1", "level": "info"}
    out = proc(None, "info", dict(event_dict))
    assert out == event_dict  # 素通し(後続 processor へ影響しない)
    res = ring.read()
    assert len(res.entries) == 1
    e = res.entries[0]
    assert e["msg"] == "summary_complete"
    assert e["payload"]["source_id"] == "s1"


# ---------------------------------------------------------------------------
# DevBroker (§7.5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broker_first_last_sub_hooks():
    broker = DevBroker()
    broker.set_loop(asyncio.get_running_loop())
    fired: list[str] = []
    broker.on_first_sub(lambda: fired.append("start"))
    broker.on_last_unsub(lambda: fired.append("stop"))

    s1 = broker.subscribe()
    s2 = broker.subscribe()
    broker.unsubscribe(s1)
    broker.unsubscribe(s2)
    assert fired == ["start", "stop"]


@pytest.mark.asyncio
async def test_broker_delivers_entries_and_flushes_slow_consumer():
    broker = DevBroker(slow_limit=5)
    broker.set_loop(asyncio.get_running_loop())
    sub = broker.subscribe()

    broker.publish_threadsafe({"event": "entry", "data": {"seq": 1}})
    await asyncio.sleep(0)
    ev = sub.queue.get_nowait()
    assert ev["event"] == "entry"

    # slow consumer: 上限を超えると flush + gap 通知のみ残る
    for i in range(2, 12):
        broker.publish_threadsafe({"event": "entry", "data": {"seq": i}})
    await asyncio.sleep(0)
    drained = []
    while not sub.queue.empty():
        drained.append(sub.queue.get_nowait())
    assert any(e["event"] == "gap" for e in drained)
    broker.unsubscribe(sub)

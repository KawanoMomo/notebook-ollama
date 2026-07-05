"""開発者モード API の統合テスト(spec §9 / §11 / §14)。

TestClient のリクエストは testclient ホスト扱いだが、guard は client.host を
見るため、テストでは `client_host="127.0.0.1"` を明示する。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.dev_logs.ring import ring as dev_ring
from core.settings_store import settings_path


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    with TestClient(create_app(), client=("127.0.0.1", 50000)) as c:
        yield c
    # singleton を汚さない
    dev_ring.disable()
    dev_ring.clear()


@pytest.fixture
def lan_client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    with TestClient(create_app(), client=("192.168.1.50", 50000)) as c:
        yield c
    dev_ring.disable()
    dev_ring.clear()


def _enable(client, capacity: int | None = None) -> dict:
    body: dict = {"enabled": True}
    if capacity is not None:
        body["log_capacity_bytes"] = capacity
    r = client.put("/api/settings/dev", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_dev_api_403_when_disabled(client):
    for path in ("/api/dev/stats", "/api/dev/range", "/api/dev/system"):
        r = client.get(path)
        assert r.status_code == 403, path
        assert r.json()["error"]["code"] == "dev.unauthorized"


def test_dev_api_403_from_lan_even_when_enabled(lan_client):
    # LAN からは設定 PUT 自体は通る(設定 API は dev guard 対象外)が、dev API は 403
    r = lan_client.put("/api/settings/dev", json={"enabled": True})
    assert r.status_code == 200
    assert lan_client.get("/api/dev/stats").status_code == 403


def test_put_dev_enables_ring_and_persists(client, tmp_path):
    out = _enable(client, capacity=5 * 1024 * 1024)
    assert out == {"enabled": True, "log_capacity_bytes": 5 * 1024 * 1024}
    assert dev_ring.enabled is True

    saved = json.loads(settings_path(tmp_path).read_text(encoding="utf-8"))
    assert saved["dev"]["enabled"] is True

    got = client.get("/api/settings").json()
    assert got["dev"]["enabled"] is True
    assert got["dev"]["log_capacity_bytes"] == 5 * 1024 * 1024


def test_capacity_is_clamped_not_rejected(client):
    out = _enable(client, capacity=999 * 1024 * 1024)  # 200MB 超
    assert out["log_capacity_bytes"] == 200 * 1024 * 1024
    out2 = client.put(
        "/api/settings/dev", json={"enabled": True, "log_capacity_bytes": 1}
    ).json()
    assert out2["log_capacity_bytes"] == 1 * 1024 * 1024


def test_stats_range_and_clear_roundtrip(client):
    _enable(client)
    # 直近のログ(設定 PUT 自体の HTTP アクセス等)が ring に入っている
    # 確実にするため 1 件明示的に積む
    from core.dev_logs.broker import broker as dev_broker
    from core.dev_logs.sink import push_dev_entry

    for i in range(5):
        push_dev_entry(
            ring=dev_ring, broker=dev_broker, level="info", source="app",
            msg=f"probe-{i}", payload={"i": i},
        )

    stats = client.get("/api/dev/stats").json()
    assert stats["enabled"] is True
    assert stats["entries"] >= 5

    rng = client.get("/api/dev/range", params={"limit": 3, "order": "desc"}).json()
    assert len(rng["entries"]) == 3
    seqs = [e["seq"] for e in rng["entries"]]
    assert seqs == sorted(seqs, reverse=True)

    cleared = client.post("/api/dev/clear").json()
    assert cleared["entries"] == 0
    # next_seq は巻き戻らない(I3)。stats 取得後の HTTP アクセス自体も
    # ring に記録されるため「以上」で検証する
    assert cleared["next_seq"] >= stats["next_seq"]


def test_disable_turns_off_collection(client):
    _enable(client)
    r = client.put("/api/settings/dev", json={"enabled": False})
    assert r.status_code == 200
    assert dev_ring.enabled is False
    assert client.get("/api/dev/stats").status_code == 403


def test_export_ndjson_has_attachment_disposition(client):
    _enable(client)
    from core.dev_logs.sink import push_dev_entry

    push_dev_entry(
        ring=dev_ring, broker=None, level="info", source="app",
        msg="export-probe", payload={},
    )
    r = client.get("/api/dev/export.ndjson")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")
    lines = [ln for ln in r.text.splitlines() if ln.strip()]
    assert any(json.loads(ln)["msg"] == "export-probe" for ln in lines)


def test_dev_settings_restored_on_startup(tmp_path, monkeypatch):
    """settings.json の dev セクションが起動時に復元され、収集が始まる(FR-6/§11 S1)。"""
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    settings_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    settings_path(tmp_path).write_text(
        json.dumps({"dev": {"enabled": True, "log_capacity_bytes": 2 * 1024 * 1024}}),
        encoding="utf-8",
    )
    try:
        with TestClient(create_app(), client=("127.0.0.1", 50000)) as c:
            got = c.get("/api/settings").json()["dev"]
            assert got["enabled"] is True
            assert got["log_capacity_bytes"] == 2 * 1024 * 1024
            assert dev_ring.enabled is True
            assert c.get("/api/dev/stats").status_code == 200
    finally:
        dev_ring.disable()
        dev_ring.clear()


def test_sse_broker_publish_is_mirrored(client):
    """SseBroker.publish が source=events で ring に入る(spec §8.3)。"""
    _enable(client)
    import anyio

    ctx = client.app.state.ctx

    async def _pub():
        await ctx.sse.publish("notebook:nb1", {"source_id": "s1", "status": "ready"})

    anyio.from_thread.run  # noqa: B018 — TestClient 内は同期なので直接 run する
    import asyncio

    asyncio.run(_pub())
    res = dev_ring.read(limit=1000)
    events = [e for e in res.entries if e["source"] == "events"]
    assert events, "SSE mirror entry not found"
    assert events[-1]["payload"]["topic"] == "notebook:nb1"

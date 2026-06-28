"""仕様 §3: source_ids が空配列のとき、send_message は 400 を返す。

旧挙動「空配列 = 全ソース検索」は廃止する。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")

    class _FakeOllamaClient:
        def __init__(self, *, endpoint, timeout=None):
            pass

        async def show(self, model):
            return {"parameters": "num_ctx 8192"}

    monkeypatch.setattr("apps.api.routers.chat.OllamaClient", _FakeOllamaClient)

    with TestClient(create_app()) as c:
        yield c


def test_empty_source_ids_returns_400(client):
    nb = client.post("/api/notebooks", json={"name": "N"}).json()
    conv = client.post(f"/api/notebooks/{nb['id']}/conversations").json()
    r = client.post(
        f"/api/notebooks/{nb['id']}/conversations/{conv['id']}/messages",
        json={"content": "質問", "source_ids": []},
    )
    assert r.status_code == 400
    body = r.json()
    # AppError は {"error": {"code","message",...}} を返す
    assert "error" in body or "detail" in body


def test_missing_source_ids_returns_400(client):
    nb = client.post("/api/notebooks", json={"name": "N"}).json()
    conv = client.post(f"/api/notebooks/{nb['id']}/conversations").json()
    r = client.post(
        f"/api/notebooks/{nb['id']}/conversations/{conv['id']}/messages",
        json={"content": "質問"},
    )
    # source_ids がない = 0 件と同じ扱い → 400
    assert r.status_code == 400

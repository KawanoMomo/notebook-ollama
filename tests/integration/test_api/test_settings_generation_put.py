"""PUT /api/settings/generation の挙動。

設定画面に generation.response_budget_tokens の表示はあるのに変更手段が
無かった(2026-07-05 実機FB)。UI から変更 → in-memory 反映 + settings.json
永続化 + 再起動時復元、の3点を保証する。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.settings_store import settings_path


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    with TestClient(create_app()) as c:
        yield c


def test_put_generation_updates_memory_and_persists(client, tmp_path):
    r = client.put(
        "/api/settings/generation", json={"response_budget_tokens": 4096}
    )
    assert r.status_code == 200, r.text
    assert r.json()["response_budget_tokens"] == 4096

    # in-memory 反映(GET が新値を返す)
    got = client.get("/api/settings").json()
    assert got["generation"]["response_budget_tokens"] == 4096

    # settings.json へ永続化
    saved = json.loads(settings_path(tmp_path).read_text(encoding="utf-8"))
    assert saved["generation"]["response_budget_tokens"] == 4096


def test_put_generation_rejects_too_small_budget(client):
    r = client.put("/api/settings/generation", json={"response_budget_tokens": 16})
    assert r.status_code == 422


def test_put_generation_can_update_ratio_together(client):
    r = client.put(
        "/api/settings/generation",
        json={"response_budget_tokens": 2048, "context_budget_ratio": 0.7},
    )
    assert r.status_code == 200, r.text
    got = client.get("/api/settings").json()["generation"]
    assert got["context_budget_ratio"] == 0.7
    assert got["response_budget_tokens"] == 2048


def test_generation_overrides_restored_on_startup(tmp_path, monkeypatch):
    """settings.json の generation セクションが起動時に AppConfig へ適用される。"""
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    settings_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    settings_path(tmp_path).write_text(
        json.dumps({"generation": {"response_budget_tokens": 8192}}),
        encoding="utf-8",
    )
    with TestClient(create_app()) as c:
        got = c.get("/api/settings").json()["generation"]
        assert got["response_budget_tokens"] == 8192

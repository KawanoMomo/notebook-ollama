"""Ollama タイムアウト値の取得/更新 API。

GPT-OSS:20B など大型モデルは Ollama のロードに 120 秒以上掛かりがちで、
chat 送信時の OllamaClient.show / chat_stream が ReadTimeout で死ぬ。
ユーザーが UI から timeout を伸ばせるよう、設定 API に項目を追加する。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.settings_store import load_overrides


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    with TestClient(create_app()) as c:
        yield c


def test_get_settings_exposes_timeouts(client):
    r = client.get("/api/settings")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "request_timeout_seconds" in body["ollama"]
    assert "chat_read_timeout_seconds" in body["ollama"]
    # 既定値の妥当性: 新既定 600 秒 (20B モデルの初回ロードを許容)
    assert body["ollama"]["request_timeout_seconds"] == 600.0
    assert body["ollama"]["chat_read_timeout_seconds"] == 600.0


def test_put_timeouts_persists_to_settings_json(client, tmp_path):
    r = client.put(
        "/api/settings/ollama/timeouts",
        json={"request_timeout_seconds": 900, "chat_read_timeout_seconds": 1800},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["request_timeout_seconds"] == 900.0
    assert body["chat_read_timeout_seconds"] == 1800.0

    # 永続化(settings.json)に書かれていること
    persisted = load_overrides(tmp_path).get("ollama", {})
    assert persisted.get("request_timeout_seconds") == 900.0
    assert persisted.get("chat_read_timeout_seconds") == 1800.0


def test_put_timeouts_rejects_zero_or_negative(client):
    r = client.put(
        "/api/settings/ollama/timeouts",
        json={"request_timeout_seconds": 0, "chat_read_timeout_seconds": 600},
    )
    assert r.status_code in (400, 422), r.text


def test_put_timeouts_rejects_excessively_large(client):
    # 24 時間以上は受け付けない(誤入力ガード)
    r = client.put(
        "/api/settings/ollama/timeouts",
        json={
            "request_timeout_seconds": 90_000,
            "chat_read_timeout_seconds": 600,
        },
    )
    assert r.status_code in (400, 422), r.text


def test_put_timeouts_updates_in_memory_config(client):
    r = client.put(
        "/api/settings/ollama/timeouts",
        json={"request_timeout_seconds": 750, "chat_read_timeout_seconds": 900},
    )
    assert r.status_code == 200
    ctx = client.app.state.ctx
    assert ctx.config.ollama.request_timeout_seconds == 750
    assert ctx.config.ollama.chat_read_timeout_seconds == 900

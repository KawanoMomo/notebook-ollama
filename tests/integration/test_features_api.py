from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_list_features(client):
    res = client.get("/api/features")
    assert res.status_code == 200
    ids = [f["id"] for f in res.json()["features"]]
    assert "table-figure-rag" in ids


def test_put_optin_roundtrip(client):
    res = client.put("/api/features/table-figure-rag", json={"enabled": True})
    assert res.status_code == 200
    res = client.get("/api/features")
    row = next(f for f in res.json()["features"] if f["id"] == "table-figure-rag")
    assert row["enabled"] is True


def test_put_unknown_flag_404(client):
    assert client.put("/api/features/nope", json={"enabled": True}).status_code == 404


def test_require_feature_blocks_when_disabled(client):
    client.put("/api/features/table-figure-rag", json={"enabled": False})
    # Task 8 で reingest がこのゲートを使う。ここではゲート単体を検証するため
    # テスト用の一時ルートではなく、ゲート適用済みの実APIを対象にする。
    # Task 8 完了までは xfail マークで先行登録する。
    pytest.xfail("gated API lands in Task 8 (reingest)")

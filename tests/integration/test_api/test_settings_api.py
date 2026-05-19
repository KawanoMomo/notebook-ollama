import pytest
from fastapi.testclient import TestClient
from apps.api.main import create_app

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        yield c

def test_get_settings_returns_defaults(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    s = r.json()
    assert s["generation"]["response_budget_tokens"] == 1024
    assert s["retrieval"]["top_k"] == 8

def test_get_stats(client):
    r = client.get("/api/stats")
    assert r.status_code == 200
    body = r.json()
    assert "notebook_count" in body
    assert "source_count" in body

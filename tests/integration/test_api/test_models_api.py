import pytest
import respx
import httpx
from fastapi.testclient import TestClient

from apps.api.main import create_app

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    app = create_app()
    with TestClient(app) as c:
        yield c

def test_list_models_returns_tags_with_recommendations(client):
    with respx.mock(assert_all_called=True) as router:
        router.get("http://fake/api/tags").mock(
            return_value=httpx.Response(200, json={
                "models": [
                    {"name": "qwen2.5:14b", "size": 1, "modified_at": "2026-05-01T00:00:00Z",
                     "details": {"family": "qwen", "parameter_size": "14B"}},
                ]
            })
        )
        router.post("http://fake/api/show").mock(
            return_value=httpx.Response(200, json={
                "parameters": "num_ctx 32768",
                "details": {"family": "qwen", "parameter_size": "14B"},
            })
        )
        r = client.get("/api/models")
    assert r.status_code == 200
    body = r.json()
    assert body["models"][0]["name"] == "qwen2.5:14b"
    assert body["models"][0]["context_window"] == 32768
    assert "japanese" in body["models"][0]["recommended_for"]

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.mcp.auth import ensure_token

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        yield c

def test_mcp_messages_rejects_missing_token(client):
    r = client.post("/mcp/messages", content=b"{}")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "mcp.unauthorized"

def test_mcp_sse_rejects_wrong_token(client, tmp_path):
    r = client.get("/mcp/sse", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401

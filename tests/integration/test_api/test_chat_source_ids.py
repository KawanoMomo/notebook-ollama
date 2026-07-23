import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")

    # Stub OllamaClient.show so num_ctx resolution stays offline
    class _FakeOllamaClient:
        def __init__(self, *, endpoint, timeout=None):
            pass

        async def show(self, model):
            return {"parameters": "num_ctx 8192"}

    monkeypatch.setattr("apps.api.routers.chat.OllamaClient", _FakeOllamaClient)

    with TestClient(create_app()) as c:
        yield c


async def test_send_message_forwards_source_ids(client):
    ctx = client.app.state.ctx
    nb = client.post("/api/notebooks", json={"name": "N"}).json()
    conv = client.post(f"/api/notebooks/{nb['id']}/conversations").json()

    captured = {}

    async def fake_run(**kwargs):
        captured.update(kwargs)
        from core.generation.stream import GenerationEvent

        yield GenerationEvent(kind="retrieval", data={"hits": []})
        yield GenerationEvent(
            kind="done",
            data={
                "answer": "",
                "citations": [],
                "model_used": "m",
                "dropped_history": 0,
                "truncated": False,
                "continued_rounds": 0,
            },
        )

    ctx.generation.run = fake_run

    with client.stream(
        "POST",
        f"/api/notebooks/{nb['id']}/conversations/{conv['id']}/messages",
        json={"content": "質問", "source_ids": ["SRC_A"]},
    ) as resp:
        for _ in resp.iter_lines():
            pass

    assert captured["source_ids"] == ["SRC_A"]

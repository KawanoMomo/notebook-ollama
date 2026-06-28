import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_ping_factory_emits_named_ping_event():
    from apps.api.routers.chat import _ping_event

    sse = _ping_event()
    rendered = sse.encode()
    assert b"event: ping" in rendered
    assert b"data: {}" in rendered


def test_chat_streaming_returns_sse(client):
    nb_id = client.post(
        "/api/notebooks", json={"name": "N", "default_model": "qwen2.5:14b"}
    ).json()["id"]
    conv_id = client.post(f"/api/notebooks/{nb_id}/conversations").json()["id"]

    payloads = b"".join(
        [
            b'{"message":{"content":"\xe5\x9b\x9e\xe7\xad\x94"},"done":false}\n',
            b'{"message":{"content":"\xe3\x81\xa7\xe3\x81\x99"},"done":true}\n',
        ]
    )
    with respx.mock() as router:
        router.post("http://fake/api/show").mock(
            return_value=httpx.Response(200, json={"parameters": "num_ctx 4096"})
        )
        router.post("http://fake/api/embeddings").mock(
            return_value=httpx.Response(200, json={"embedding": [0.1] * 1024})
        )
        router.post("http://fake/api/chat").mock(return_value=httpx.Response(200, content=payloads))
        r = client.post(
            f"/api/notebooks/{nb_id}/conversations/{conv_id}/messages",
            # source_ids が空だと 400 (旧「空=全選択」廃止 §3) のため、ダミー1件を渡す
            json={"content": "質問", "source_ids": ["SRC_DUMMY"]},
        )
        assert r.status_code == 200
        body = r.text
        assert "event: retrieval" in body
        assert "event: done" in body
        assert "回答" in body or "\\u56de" in body

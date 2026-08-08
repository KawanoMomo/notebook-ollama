"""選択範囲翻訳エンドポイントの契約。"""

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_translate_returns_sse_stream(client):
    res = client.post("/api/translate", json={"text": "Hello", "target_lang": "ja"})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    # Ollama 未起動でも done イベントで必ず終端する(閲覧を止めない)
    assert "data:" in res.text
    assert '"done": true' in res.text.replace('"done":true', '"done": true')


def test_translate_rejects_too_long_text(client):
    res = client.post("/api/translate", json={"text": "x" * 5000, "target_lang": "ja"})
    assert res.status_code == 400


def test_translate_conflicts_while_stream_running(client):
    from core.generation.stream_registry import mark_running

    with mark_running("conv-1"):
        res = client.post(
            "/api/translate",
            json={"text": "Hello", "target_lang": "ja", "conversation_id": "conv-1"},
        )
    assert res.status_code == 409


def test_translate_runs_when_other_conversation_is_generating(client):
    from core.generation.stream_registry import mark_running

    with mark_running("conv-other"):
        res = client.post(
            "/api/translate",
            json={"text": "Hello", "target_lang": "ja", "conversation_id": "conv-1"},
        )
    assert res.status_code == 200

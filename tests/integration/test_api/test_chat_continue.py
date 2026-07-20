import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    # 自動継続を無効化し「1回で truncated 保存」を決定的に作る
    monkeypatch.setenv("NOTEBOOK_OLLAMA_GENERATION__AUTO_CONTINUE_MAX", "0")
    app = create_app()
    with TestClient(app) as c:
        yield c


def _mock_show_embed(router):
    router.post("http://fake/api/show").mock(
        return_value=httpx.Response(200, json={"parameters": "num_ctx 4096"})
    )
    router.post("http://fake/api/embeddings").mock(
        return_value=httpx.Response(200, json={"embedding": [0.1] * 1024})
    )


def _setup_truncated_conv(client):
    nb_id = client.post(
        "/api/notebooks", json={"name": "N", "default_model": "qwen2.5:14b"}
    ).json()["id"]
    conv_id = client.post(f"/api/notebooks/{nb_id}/conversations").json()["id"]
    with respx.mock() as router:
        _mock_show_embed(router)
        router.post("http://fake/api/chat").mock(
            return_value=httpx.Response(
                200,
                content=b'{"message":{"content":"\xe9\x80\x94\xe4\xb8\xad"},"done":true,"done_reason":"length"}\n',
            )
        )
        r = client.post(
            f"/api/notebooks/{nb_id}/conversations/{conv_id}/messages",
            json={"content": "質問", "source_ids": ["SRC_DUMMY"]},
        )
        assert r.status_code == 200
    return nb_id, conv_id


def test_continue_appends_to_last_message_and_clears_truncated(client):
    nb_id, conv_id = _setup_truncated_conv(client)
    before = client.get(
        f"/api/notebooks/{nb_id}/conversations/{conv_id}/messages"
    ).json()
    assert before[-1]["truncated"] is True
    with respx.mock() as router:
        _mock_show_embed(router)
        router.post("http://fake/api/chat").mock(
            return_value=httpx.Response(
                200,
                content=b'{"message":{"content":"\xe3\x81\xa8\xe7\xb6\x9a\xe3\x81\x8d"},"done":true,"done_reason":"stop"}\n',
            )
        )
        r = client.post(
            f"/api/notebooks/{nb_id}/conversations/{conv_id}/continue",
            json={"source_ids": ["SRC_DUMMY"]},
        )
        assert r.status_code == 200
    after = client.get(
        f"/api/notebooks/{nb_id}/conversations/{conv_id}/messages"
    ).json()
    assert len(after) == len(before)          # メッセージは増えない(追記更新)
    assert after[-1]["truncated"] is False
    assert "途中" in after[-1]["content"] and "と続き" in after[-1]["content"]
    assert "打ち切られました" not in after[-1]["content"]  # 旧注記は除去される


def test_continue_409_when_last_is_not_truncated(client):
    nb_id = client.post(
        "/api/notebooks", json={"name": "N", "default_model": "qwen2.5:14b"}
    ).json()["id"]
    conv_id = client.post(f"/api/notebooks/{nb_id}/conversations").json()["id"]
    r = client.post(
        f"/api/notebooks/{nb_id}/conversations/{conv_id}/continue",
        json={"source_ids": ["SRC_DUMMY"]},
    )
    assert r.status_code == 409


def test_continue_404_when_conversation_not_in_notebook(client):
    nb_id, _conv_id = _setup_truncated_conv(client)
    r = client.post(
        f"/api/notebooks/{nb_id}/conversations/no-such-conv/continue",
        json={"source_ids": ["SRC_DUMMY"]},
    )
    assert r.status_code == 404

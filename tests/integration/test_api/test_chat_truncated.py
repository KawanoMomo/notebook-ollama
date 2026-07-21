import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    # 既定値(auto_continue_max=2)が将来変わってもこのテストの respx 応答数
    # (初回+継続2回=3)が巻き込まれないよう明示 pin する(トリアージ#8)。
    monkeypatch.setenv("NOTEBOOK_OLLAMA_GENERATION__AUTO_CONTINUE_MAX", "2")
    app = create_app()
    with TestClient(app) as c:
        yield c


def _length_chat_response():
    # done_reason=length を返す1ラウンド分の /api/chat 応答
    return httpx.Response(
        200,
        content=b'{"message":{"content":"x"},"done":true,"done_reason":"length"}\n',
    )


def test_chat_persists_truncated_flag_and_returns_in_messages(client):
    nb_id = client.post(
        "/api/notebooks", json={"name": "N", "default_model": "qwen2.5:14b"}
    ).json()["id"]
    conv_id = client.post(f"/api/notebooks/{nb_id}/conversations").json()["id"]
    with respx.mock() as router:
        router.post("http://fake/api/show").mock(
            return_value=httpx.Response(200, json={"parameters": "num_ctx 4096"})
        )
        router.post("http://fake/api/embeddings").mock(
            return_value=httpx.Response(200, json={"embedding": [0.1] * 1024})
        )
        # 初回+自動継続2回、すべて length で打ち切り
        router.post("http://fake/api/chat").mock(
            side_effect=[_length_chat_response() for _ in range(3)]
        )
        r = client.post(
            f"/api/notebooks/{nb_id}/conversations/{conv_id}/messages",
            json={"content": "質問", "source_ids": ["SRC_DUMMY"]},
        )
        assert r.status_code == 200
        assert "event: continuing" in r.text  # 自動継続イベントが流れる
    msgs = client.get(
        f"/api/notebooks/{nb_id}/conversations/{conv_id}/messages"
    ).json()
    assert msgs[-1]["role"] == "assistant"
    assert msgs[-1]["truncated"] is True

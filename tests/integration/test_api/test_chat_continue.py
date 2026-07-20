import json

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


def test_continue_409_when_no_messages(client):
    # 会話にメッセージが一件もない(=継続対象が存在しない)ケース
    nb_id = client.post(
        "/api/notebooks", json={"name": "N", "default_model": "qwen2.5:14b"}
    ).json()["id"]
    conv_id = client.post(f"/api/notebooks/{nb_id}/conversations").json()["id"]
    r = client.post(
        f"/api/notebooks/{nb_id}/conversations/{conv_id}/continue",
        json={"source_ids": ["SRC_DUMMY"]},
    )
    assert r.status_code == 409


def test_continue_409_when_last_completed_not_truncated(client):
    # 最後の assistant 応答が done_reason=stop で正常完了しているケース
    # (truncated=False) は継続対象がないため 409
    nb_id = client.post(
        "/api/notebooks", json={"name": "N", "default_model": "qwen2.5:14b"}
    ).json()["id"]
    conv_id = client.post(f"/api/notebooks/{nb_id}/conversations").json()["id"]
    with respx.mock() as router:
        _mock_show_embed(router)
        router.post("http://fake/api/chat").mock(
            return_value=httpx.Response(
                200,
                content=b'{"message":{"content":"\xe5\x9b\x9e\xe7\xad\x94"},"done":true,"done_reason":"stop"}\n',
            )
        )
        r = client.post(
            f"/api/notebooks/{nb_id}/conversations/{conv_id}/messages",
            json={"content": "質問", "source_ids": ["SRC_DUMMY"]},
        )
        assert r.status_code == 200
    msgs = client.get(f"/api/notebooks/{nb_id}/conversations/{conv_id}/messages").json()
    assert msgs[-1]["truncated"] is False

    r = client.post(
        f"/api/notebooks/{nb_id}/conversations/{conv_id}/continue",
        json={"source_ids": ["SRC_DUMMY"]},
    )
    assert r.status_code == 409


def test_continue_400_when_source_ids_empty(client):
    nb_id, conv_id = _setup_truncated_conv(client)
    r = client.post(
        f"/api/notebooks/{nb_id}/conversations/{conv_id}/continue",
        json={"source_ids": []},
    )
    assert r.status_code == 400


def test_continue_404_when_conversation_not_in_notebook(client):
    nb_id, _conv_id = _setup_truncated_conv(client)
    r = client.post(
        f"/api/notebooks/{nb_id}/conversations/no-such-conv/continue",
        json={"source_ids": ["SRC_DUMMY"]},
    )
    assert r.status_code == 404


def test_continue_history_includes_pair_with_duplicate_question_text(client):
    """レビュー指摘の回帰テスト: 過去の質問と最後(継続対象)の質問が同一文字列の場合、

    履歴再構築ループは msgs[:-1] を回すだけで最後の user 質問を自然にペア化しない
    (対応する assistant=last がスライスから除外されているため)。かつて存在した
    `if history and history[-1].user == question: history.pop()` は、この状況で
    過去の正当な履歴ペアまで誤って pop してしまうバグがあった。ここでは実際に
    Ollama へ送られるリクエスト body を respx で捕捉し、過去ペア
    (user:"Q" / assistant:"A1") が history として残っていることを確認する。
    """
    nb_id = client.post(
        "/api/notebooks", json={"name": "N", "default_model": "qwen2.5:14b"}
    ).json()["id"]
    conv_id = client.post(f"/api/notebooks/{nb_id}/conversations").json()["id"]

    # Turn 1: 完了応答 "A1"。質問文字列 "Q" は Turn 2 と意図的に同一にする。
    with respx.mock() as router:
        _mock_show_embed(router)
        router.post("http://fake/api/chat").mock(
            return_value=httpx.Response(
                200,
                content=b'{"message":{"content":"A1"},"done":true,"done_reason":"stop"}\n',
            )
        )
        r = client.post(
            f"/api/notebooks/{nb_id}/conversations/{conv_id}/messages",
            json={"content": "Q", "source_ids": ["SRC_DUMMY"]},
        )
        assert r.status_code == 200

    # Turn 2: 同じ質問文字列 "Q" で打ち切り応答を作る(継続対象になる)
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
            json={"content": "Q", "source_ids": ["SRC_DUMMY"]},
        )
        assert r.status_code == 200

    captured: list[bytes] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        captured.append(request.content)
        return httpx.Response(
            200,
            content=b'{"message":{"content":"\xe3\x81\xa8\xe7\xb6\x9a\xe3\x81\x8d"},"done":true,"done_reason":"stop"}\n',
        )

    with respx.mock() as router:
        _mock_show_embed(router)
        router.post("http://fake/api/chat").mock(side_effect=_capture)
        r = client.post(
            f"/api/notebooks/{nb_id}/conversations/{conv_id}/continue",
            json={"source_ids": ["SRC_DUMMY"]},
        )
        assert r.status_code == 200

    assert captured, "no /api/chat request was captured"
    payload = json.loads(captured[0])
    sent_messages = payload["messages"]
    pairs = list(zip(sent_messages, sent_messages[1:]))
    assert any(
        a.get("role") == "user"
        and a.get("content") == "Q"
        and b.get("role") == "assistant"
        and b.get("content") == "A1"
        for a, b in pairs
    ), f"expected (user:'Q', assistant:'A1') pair in history, got: {sent_messages}"

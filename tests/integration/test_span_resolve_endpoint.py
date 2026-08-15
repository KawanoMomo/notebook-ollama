"""第2段エンドポイントの契約。既存の統合テストの client フィクスチャを使う。"""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.storage import (
    chunks_repo,
    conversations_repo,
    messages_repo,
    notebooks_repo,
    sources_repo,
)

# 文が1つしかないチャンク本文。score_spans はこの場合に埋め込みを呼ばず [] を返すため、
# Ollama へ触らずにエンドポイントの契約(ステータス/形)だけを検証できる。
_SINGLE_SENTENCE_CHUNK = "これは唯一の文である。"

# 埋め込み経路を通すための本文(2文以上)。
_MULTI_SENTENCE_CHUNK = "レベル2では成果物が管理される。まったく無関係な別の話題がここにある。"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    app = create_app()
    with TestClient(app) as c:
        yield c


def _seed(client, *, chunk_text: str, chunk_id: str = "chunk-1"):
    conn = client.app.state.ctx.conn
    nb = notebooks_repo.create_notebook(conn, name="N")
    conv = conversations_repo.create_conversation(conn, notebook_id=nb.id)
    src = sources_repo.create_source(conn, notebook_id=nb.id, kind="text", title="T")
    chunk = chunks_repo.ChunkRecord(
        id=chunk_id,
        source_id=src.id,
        notebook_id=nb.id,
        ord=0,
        page=1,
        heading_path=None,
        text=chunk_text,
        token_count=10,
    )
    chunks_repo.insert_chunks(conn, [chunk])
    messages_repo.append_message(
        conn,
        conversation_id=conv.id,
        role="user",
        content="レベル2の管理について教えてください。",
    )
    msg = messages_repo.append_message(
        conn,
        conversation_id=conv.id,
        role="assistant",
        content="レベル2では成果物が管理される[^1]。",
        citations=[{"n": 1, "chunk_id": chunk.id, "source_id": src.id, "spans": []}],
        model="m",
    )
    return conv.id, msg.id


@pytest.fixture
def seeded(client):
    return _seed(client, chunk_text=_SINGLE_SENTENCE_CHUNK)


@pytest.fixture
def seeded_conversation_id(seeded):
    return seeded[0]


@pytest.fixture
def seeded_message_id(seeded):
    return seeded[1]


def test_returns_empty_spans_for_unknown_message(client):
    res = client.post(
        "/api/messages/does-not-exist/citations/1/spans", json={"answer_occurrence": 0}
    )
    assert res.status_code == 404


def test_returns_spans_shape(client, seeded_message_id):
    res = client.post(
        f"/api/messages/{seeded_message_id}/citations/1/spans",
        json={"answer_occurrence": 0},
    )
    assert res.status_code in (200, 409)
    if res.status_code == 200:
        body = res.json()
        assert body["method"] == "embedding"
        for span in body["spans"]:
            assert span["ordinal"] is None
            assert span["method"] == "embedding"
            assert span["answer_occurrence"] == 0


def test_conflicts_while_stream_running(client, seeded_message_id, seeded_conversation_id):
    from core.generation.stream_registry import mark_running

    with mark_running(seeded_conversation_id):
        res = client.post(
            f"/api/messages/{seeded_message_id}/citations/1/spans",
            json={"answer_occurrence": 0},
        )
    assert res.status_code == 409


@pytest.fixture
def compat_llm_client(tmp_path, monkeypatch):
    """LLM だけ openai-compat、埋め込みは Ollama という分離構成のアプリ。

    既定(全て Ollama)では ctx.text_embedder.gateway is ctx.ollama_gateway のため
    誤配線が露見しない。分離構成でのみ捕まえられる。"""
    import json as _json

    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    (tmp_path / "settings.json").write_text(
        _json.dumps(
            {
                "ollama": {
                    "default_model": "qwen2.5:14b",
                    "embedding_model": "bge-m3",
                    "embedding_dim": 1024,
                    "runtime_backend": "openai-compat",
                    "openai_compat_endpoint": "http://compat",
                }
            }
        ),
        encoding="utf-8",
    )
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_span_embedding_uses_embed_gateway_not_llm_gateway(compat_llm_client):
    """第2段の埋め込みは text_embedder 側 gateway(Ollama)を通り、生成用の
    openai-compat エンドポイントへは飛ばない(ADR-018 の再発防止)。"""
    from core.ollama.client import OllamaClient
    from core.ollama.openai_compat import OpenAICompatClient

    ctx = compat_llm_client.app.state.ctx
    assert isinstance(ctx.ollama_gateway._client, OpenAICompatClient)
    assert isinstance(ctx.text_embedder.gateway._client, OllamaClient)
    assert ctx.text_embedder.gateway is not ctx.ollama_gateway

    _, message_id = _seed(
        compat_llm_client, chunk_text=_MULTI_SENTENCE_CHUNK, chunk_id="chunk-embed-compat"
    )

    def _embedding(request: httpx.Request) -> httpx.Response:
        import json as _json

        text = _json.loads(request.content)["prompt"]
        vec = [1.0, 0.0] if "無関係" not in text else [0.0, 1.0]
        return httpx.Response(200, json={"embedding": vec})

    with respx.mock(assert_all_called=False) as router:
        ollama_route = router.post("http://fake/api/embeddings").mock(side_effect=_embedding)
        compat_route = router.post("http://compat/v1/embeddings").mock(
            return_value=httpx.Response(404)
        )
        res = compat_llm_client.post(
            f"/api/messages/{message_id}/citations/1/spans",
            json={"answer_occurrence": 0},
        )

    assert res.status_code == 200
    assert ollama_route.called
    assert not compat_route.called
    body = res.json()
    assert len(body["spans"]) == 1
    assert body["spans"][0]["quote"] == "レベル2では成果物が管理される。"


def test_returns_embedding_span_with_requested_occurrence(client):
    """埋め込み経路: 一致文が1件返り、answer_occurrence が要求値で上書きされる。"""
    # モジュール level の SpanCache を跨がないよう chunk_id を分ける
    _, message_id = _seed(client, chunk_text=_MULTI_SENTENCE_CHUNK, chunk_id="chunk-embed")

    def _embedding(request: httpx.Request) -> httpx.Response:
        import json as _json

        text = _json.loads(request.content)["prompt"]
        vec = [1.0, 0.0] if "無関係" not in text else [0.0, 1.0]
        return httpx.Response(200, json={"embedding": vec})

    with respx.mock() as router:
        router.post("http://fake/api/embeddings").mock(side_effect=_embedding)
        res = client.post(
            f"/api/messages/{message_id}/citations/1/spans",
            json={"answer_occurrence": 0},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["method"] == "embedding"
    assert len(body["spans"]) == 1
    span = body["spans"][0]
    assert span["quote"] == "レベル2では成果物が管理される。"
    assert span["ordinal"] is None
    assert span["method"] == "embedding"
    assert span["answer_occurrence"] == 0

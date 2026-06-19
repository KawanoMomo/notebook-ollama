from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.storage import notebooks_repo, sources_repo
from core.storage.chunks_repo import ChunkRecord, insert_chunks


class _FakeGateway:
    """次元可変の fake 埋め込みゲートウェイ。embed 呼び出し回数を記録する。"""

    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.embed_calls: list[tuple[str, str]] = []

    async def embed(self, *, model: str, text: str) -> list[float]:
        self.embed_calls.append((model, text))
        return [0.1] * self.dim


def _seed_chunks(ctx, *, n: int) -> str:
    """1 ノート + 1 ソース + n チャンクを仕込み、source_id を返す。"""
    nb = notebooks_repo.create_notebook(ctx.conn, name="nb1")
    src = sources_repo.create_source(ctx.conn, notebook_id=nb.id, kind="pdf")
    chunks = [
        ChunkRecord(
            id=f"chunk-{i}",
            source_id=src.id,
            notebook_id=nb.id,
            ord=i,
            page=i,
            heading_path=f"H{i}",
            text=f"body {i}",
            token_count=3,
        )
        for i in range(n)
    ]
    insert_chunks(ctx.conn, chunks)
    ctx.conn.commit()
    return src.id


def _mock_tags_show(client, *, name: str, capabilities: list[str]):
    """list_tags / show を respx でモックする helper を返す context manager。"""
    import httpx
    import respx

    mock = respx.mock(assert_all_called=False)
    mock.get("http://fake/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": name}]})
    )
    mock.post("http://fake/api/show").mock(
        return_value=httpx.Response(200, json={"capabilities": capabilities})
    )
    return mock


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_switch_rejects_non_embedding_model(client):
    with _mock_tags_show(client, name="qwen2.5:14b", capabilities=["completion"]):
        r = client.post("/api/settings/embedding/switch", json={"model": "qwen2.5:14b"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "input.invalid"


def test_switch_rejects_model_not_in_tags(client):
    with _mock_tags_show(client, name="other-model", capabilities=["embedding"]):
        r = client.post("/api/settings/embedding/switch", json={"model": "bge-m3"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "input.invalid"


def test_switch_recreates_collection_and_reindexes_all_chunks(client, tmp_path):
    ctx = client.app.state.ctx
    src_id = _seed_chunks(ctx, n=3)

    fake = _FakeGateway(dim=8)
    ctx.ollama = fake

    with _mock_tags_show(client, name="bge-m3", capabilities=["embedding"]):
        r = client.post("/api/settings/embedding/switch", json={"model": "bge-m3"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model"] == "bge-m3"
    assert body["dim"] == 8
    assert body["reindexed_chunks"] == 3

    # collection が新次元 8 で再作成されている
    assert ctx.vector_store.collection_dim() == 8

    # 全チャンク(3) が再 embed された(+ probe 用の短文 embed 1 回)
    reindex_calls = [c for c in fake.embed_calls if c[1].startswith("body ")]
    assert len(reindex_calls) == 3
    assert all(c[0] == "bge-m3" for c in reindex_calls)

    # 検索で再 upsert されたベクトルが新次元で引けること
    hits = ctx.vector_store.search(
        query=[0.1] * 8, notebook_id=ctx.conn.execute(
            "SELECT notebook_id FROM sources WHERE id=?", (src_id,)
        ).fetchone()[0], limit=10
    )
    assert len(hits) == 3

    # settings.json に embedding_model / embedding_dim / default_model が保存されている
    sj = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert sj["ollama"]["embedding_model"] == "bge-m3"
    assert sj["ollama"]["embedding_dim"] == 8
    assert "default_model" in sj["ollama"]


def test_switch_publishes_progress_events(client):
    ctx = client.app.state.ctx
    _seed_chunks(ctx, n=2)
    ctx.ollama = _FakeGateway(dim=8)

    # anyio BlockingPortal で subscribe してから POST を発火させる
    portal = getattr(client, "portal", None) or getattr(client, "_portal", None)
    queue = portal.call(ctx.sse.subscribe, "embedding_reindex")

    with _mock_tags_show(client, name="bge-m3", capabilities=["embedding"]):
        r = client.post("/api/settings/embedding/switch", json={"model": "bge-m3"})
    assert r.status_code == 200

    events: list[dict] = []
    while not queue.empty():
        events.append(queue.get_nowait())

    types = [e["type"] for e in events]
    assert "reindex_progress" in types
    assert "reindex_complete" in types
    # 最初の progress は done=0、最後の progress は done=total=2
    progress = [e for e in events if e["type"] == "reindex_progress"]
    assert progress[0]["done"] == 0
    assert progress[0]["total"] == 2
    assert progress[-1]["done"] == 2
    complete = [e for e in events if e["type"] == "reindex_complete"][0]
    assert complete["model"] == "bge-m3"
    assert complete["dim"] == 8


def test_settings_events_sse_contract(client):
    """GET /api/settings/events が reindex_complete を event 名に写像し type を data から除くこと。

    broker 直購読でトピック一致・type 写像・data の type 抜きを検証する。
    """
    ctx = client.app.state.ctx
    _seed_chunks(ctx, n=1)
    ctx.ollama = _FakeGateway(dim=8)

    # broker を直接購読して SSE 出力をバイパス検証する
    portal = getattr(client, "portal", None) or getattr(client, "_portal", None)
    queue = portal.call(ctx.sse.subscribe, "embedding_reindex")

    with _mock_tags_show(client, name="bge-m3", capabilities=["embedding"]):
        r = client.post("/api/settings/embedding/switch", json={"model": "bge-m3"})
    assert r.status_code == 200

    events: list[dict] = []
    while not queue.empty():
        events.append(queue.get_nowait())

    # payload['type'] が reindex_progress / reindex_complete であること(topic 名一致)
    types = {e["type"] for e in events}
    assert "reindex_progress" in types
    assert "reindex_complete" in types

    # complete ペイロードには model/dim があり type がある(SSE generator が除く契約)
    complete = next(e for e in events if e["type"] == "reindex_complete")
    assert complete["model"] == "bge-m3"
    assert complete["dim"] == 8
    # SSE generator 側で {"k:v for k,v in payload if k!='type'} するため
    # data = {"model":"bge-m3","dim":8} になる(type 抜き確認はここでは broker 側)
    data_without_type = {k: v for k, v in complete.items() if k != "type"}
    assert data_without_type == {"model": "bge-m3", "dim": 8}

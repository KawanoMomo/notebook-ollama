from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.routers.settings import settings_events
from core.ollama.gateway import reset_embedding_dim_cache
from core.storage import notebooks_repo, sources_repo
from core.storage.chunks_repo import ChunkRecord, insert_chunks


@pytest.fixture(autouse=True)
def _clear_dim_cache():
    """probe_embedding_dim のプロセス全体キャッシュをテスト間でリークさせない。"""
    reset_embedding_dim_cache()
    yield
    reset_embedding_dim_cache()


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


def test_switch_preserves_channel_payload(client):
    """再インデックスで録音 chunk の channel(mic/system)が carry-forward されること。

    回帰バグ: switch ループは channel=None でハードコードしていたため、switch 後に
    system チャンネルの引用が mic 音声(audio.py 既定 channel=mic)を再生していた。
    channel は SQLite に無い payload 専用フィールドなので、recreate 前に現行
    collection から退避して再 upsert 時に復元する必要がある。
    """
    ctx = client.app.state.ctx
    nb = notebooks_repo.create_notebook(ctx.conn, name="rec-nb")
    src = sources_repo.create_source(ctx.conn, notebook_id=nb.id, kind="recording")
    chunks = [
        ChunkRecord(
            id="mic-chunk", source_id=src.id, notebook_id=nb.id, ord=0,
            page=None, heading_path=None, text="hello mic", token_count=2,
            start_ms=0, end_ms=1000, speaker="you",
        ),
        ChunkRecord(
            id="sys-chunk", source_id=src.id, notebook_id=nb.id, ord=1,
            page=None, heading_path=None, text="hello system", token_count=2,
            start_ms=1000, end_ms=2000, speaker="other",
        ),
    ]
    insert_chunks(ctx.conn, chunks)
    ctx.conn.commit()

    # 既存 collection に channel 付きで upsert(録音取込後の状態を模す)。
    from core.storage.vector_store import ChunkVector

    old_dim = ctx.vector_store.collection_dim()
    ctx.vector_store.upsert(
        [
            ChunkVector(
                id="mic-chunk", vector=[0.1] * old_dim, notebook_id=nb.id,
                source_id=src.id, source_kind="recording", page=None,
                heading_path=None, ord=0, start_ms=0, end_ms=1000,
                speaker="you", channel="mic",
            ),
            ChunkVector(
                id="sys-chunk", vector=[0.1] * old_dim, notebook_id=nb.id,
                source_id=src.id, source_kind="recording", page=None,
                heading_path=None, ord=1, start_ms=1000, end_ms=2000,
                speaker="other", channel="system",
            ),
        ]
    )

    fake = _FakeGateway(dim=8)
    ctx.ollama = fake
    with _mock_tags_show(client, name="bge-m3", capabilities=["embedding"]):
        r = client.post("/api/settings/embedding/switch", json={"model": "bge-m3"})
    assert r.status_code == 200, r.text

    hits = ctx.vector_store.search(query=[0.1] * 8, notebook_id=nb.id, limit=10)
    by_id = {h.id: h.channel for h in hits}
    assert by_id["mic-chunk"] == "mic"
    assert by_id["sys-chunk"] == "system"


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
    complete = next(e for e in events if e["type"] == "reindex_complete")
    assert complete["model"] == "bge-m3"
    assert complete["dim"] == 8


def test_switch_publishes_complete_payload_shape(client):
    """switch の publish が reindex_complete に model/dim を内包すること(broker 直購読)。"""
    ctx = client.app.state.ctx
    _seed_chunks(ctx, n=1)
    ctx.ollama = _FakeGateway(dim=8)

    portal = getattr(client, "portal", None) or getattr(client, "_portal", None)
    queue = portal.call(ctx.sse.subscribe, "embedding_reindex")

    with _mock_tags_show(client, name="bge-m3", capabilities=["embedding"]):
        r = client.post("/api/settings/embedding/switch", json={"model": "bge-m3"})
    assert r.status_code == 200

    events: list[dict] = []
    while not queue.empty():
        events.append(queue.get_nowait())

    complete = next(e for e in events if e["type"] == "reindex_complete")
    assert complete["model"] == "bge-m3"
    assert complete["dim"] == 8


class _FakeBroker:
    """publish を即時 dispatch し、subscribe/unsubscribe を記録する最小 broker。"""

    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()
        self.subscribed: list[str] = []
        self.unsubscribed: list[tuple[str, object]] = []

    def subscribe(self, topic: str):
        self.subscribed.append(topic)
        return self.queue

    def unsubscribe(self, topic: str, q) -> None:
        self.unsubscribed.append((topic, q))


class _FakeRequest:
    """settings_events に渡す最小 Request。is_disconnected は常に False。"""

    def __init__(self, ctx) -> None:
        self.app = type("_App", (), {"state": type("_S", (), {"ctx": ctx})()})()

    async def is_disconnected(self) -> bool:
        return False


@pytest.mark.asyncio
async def test_settings_events_generator_maps_type_to_event(client):
    """ジェネレータ本体を実行し、type→event 名写像・data の type 除去・unsubscribe を検証する。

    方式 a: ルート settings_events を直接呼び、返る EventSourceResponse.body_iterator
    (= gen())を drive することで写像コードを実コードとして1回実行する。
    """
    ctx = client.app.state.ctx
    fake_broker = _FakeBroker()
    ctx.sse = fake_broker

    resp = await settings_events(_FakeRequest(ctx))  # type: ignore[arg-type]
    gen = resp.body_iterator

    # subscribe が呼ばれ、トピックが embedding_reindex であること
    assert fake_broker.subscribed == ["embedding_reindex"]

    # 各 type を publish 済みにして、ジェネレータが写像した dict を読み出す
    await fake_broker.queue.put({"type": "reindex_progress", "done": 0, "total": 2})
    out = await gen.__anext__()
    assert out == {"event": "reindex_progress", "data": json.dumps({"done": 0, "total": 2})}

    await fake_broker.queue.put({"type": "reindex_complete", "model": "bge-m3", "dim": 8})
    out = await gen.__anext__()
    assert out["event"] == "reindex_complete"
    data = json.loads(out["data"])
    assert data == {"model": "bge-m3", "dim": 8}
    assert "type" not in data  # data から type が落ちていること

    await fake_broker.queue.put({"type": "reindex_error", "message": "boom"})
    out = await gen.__anext__()
    assert out["event"] == "reindex_error"
    assert json.loads(out["data"]) == {"message": "boom"}

    # ジェネレータを閉じると finally で unsubscribe が呼ばれること
    await gen.aclose()
    assert fake_broker.unsubscribed == [("embedding_reindex", fake_broker.queue)]

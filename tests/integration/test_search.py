import pytest

from core.retrieval.search import RetrievalService
from core.storage.chunks_repo import ChunkRecord, insert_chunks
from core.storage.database import connect, migrate
from core.storage.notebooks_repo import create_notebook
from core.storage.sources_repo import create_source
from core.storage.vector_store import ChunkVector, VectorStore


class FakeGateway:
    async def embed(self, *, model: str, text: str) -> list[float]:
        return [1.0, 0.0, 0.0, 0.0]


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_retrieval_scopes_to_source_ids(tmp_path):
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    src_a = create_source(conn, notebook_id=nb.id, kind="md", title="A", content_hash="ha")
    src_b = create_source(conn, notebook_id=nb.id, kind="md", title="B", content_hash="hb")
    insert_chunks(
        conn,
        [
            ChunkRecord(
                id="a" * 26,
                source_id=src_a.id,
                notebook_id=nb.id,
                ord=0,
                page=None,
                heading_path=None,
                text="only in A",
                token_count=3,
            ),
            ChunkRecord(
                id="b" * 26,
                source_id=src_b.id,
                notebook_id=nb.id,
                ord=0,
                page=None,
                heading_path=None,
                text="only in B",
                token_count=3,
            ),
        ],
    )
    vs = VectorStore(path=tmp_path / "q", dim=4)
    vs.ensure_collection()
    vs.upsert(
        [
            ChunkVector(
                id="a" * 26,
                vector=[1, 0, 0, 0],
                notebook_id=nb.id,
                source_id=src_a.id,
                source_kind="md",
                page=None,
                heading_path=None,
                ord=0,
            ),
            ChunkVector(
                id="b" * 26,
                vector=[1, 0, 0, 0],
                notebook_id=nb.id,
                source_id=src_b.id,
                source_kind="md",
                page=None,
                heading_path=None,
                ord=0,
            ),
        ]
    )

    svc = RetrievalService(
        conn=conn, vector_store=vs, ollama=FakeGateway(), embedding_model="bge-m3"
    )
    scoped = await svc.search(notebook_id=nb.id, query="hi", limit=10, source_ids=[src_a.id])
    assert {h.source_id for h in scoped} == {src_a.id}
    unscoped = await svc.search(notebook_id=nb.id, query="hi", limit=10)
    assert {h.source_id for h in unscoped} == {src_a.id, src_b.id}


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_retrieval_returns_joined_chunks(tmp_path):
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    src = create_source(conn, notebook_id=nb.id, kind="md", title="Doc", content_hash="h")
    chunks = [
        ChunkRecord(
            id="a" * 26,
            source_id=src.id,
            notebook_id=nb.id,
            ord=0,
            page=1,
            heading_path="Ch1",
            text="hello world",
            token_count=2,
        ),
    ]
    insert_chunks(conn, chunks)
    vs = VectorStore(path=tmp_path / "q", dim=4)
    vs.ensure_collection()
    vs.upsert(
        [
            ChunkVector(
                id="a" * 26,
                vector=[1, 0, 0, 0],
                notebook_id=nb.id,
                source_id=src.id,
                source_kind="md",
                page=1,
                heading_path="Ch1",
                ord=0,
            )
        ]
    )

    svc = RetrievalService(
        conn=conn, vector_store=vs, ollama=FakeGateway(), embedding_model="bge-m3"
    )
    hits = await svc.search(notebook_id=nb.id, query="hi", limit=5)
    assert len(hits) == 1
    h = hits[0]
    assert h.text == "hello world"
    assert h.source_title == "Doc"
    assert h.page == 1
    assert h.heading_path == "Ch1"


def _figure_desc_fixture(tmp_path):
    """text チャンク1件 + figure_desc チャンク1件を索引済みの状態を作る。"""
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    src = create_source(conn, notebook_id=nb.id, kind="pdf", title="Doc", content_hash="h")
    insert_chunks(
        conn,
        [
            ChunkRecord(
                id="a" * 26, source_id=src.id, notebook_id=nb.id, ord=0,
                page=1, heading_path=None, text="本文チャンク", token_count=3,
            ),
            ChunkRecord(
                id="f" * 26, source_id=src.id, notebook_id=nb.id, ord=1,
                page=1, heading_path=None, text="図の説明チャンク", token_count=4,
                kind="figure_desc",
            ),
        ],
    )
    vs = VectorStore(path=tmp_path / "q", dim=4)
    vs.ensure_collection()
    vs.upsert(
        [
            ChunkVector(
                id="a" * 26, vector=[1, 0, 0, 0], notebook_id=nb.id,
                source_id=src.id, source_kind="pdf", page=1, heading_path=None, ord=0,
            ),
            ChunkVector(
                id="f" * 26, vector=[1, 0, 0, 0], notebook_id=nb.id,
                source_id=src.id, source_kind="pdf", page=1, heading_path=None, ord=1,
            ),
        ]
    )
    return conn, vs, nb


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_figure_desc_excluded_from_search_when_beta_off(tmp_path):
    """回帰テスト: spec「OFF時は検索から除外(kind='figure_desc'をフィルタ)」。
    フィルタ未実装だとベータOFFでも図説明チャンクが検索・引用に乗ってしまう。"""
    conn, vs, nb = _figure_desc_fixture(tmp_path)
    svc = RetrievalService(
        conn=conn, vector_store=vs, ollama=FakeGateway(), embedding_model="bge-m3",
        figure_desc_enabled=lambda: False,
    )
    hits = await svc.search(notebook_id=nb.id, query="hi", limit=10)
    assert [h.text for h in hits] == ["本文チャンク"]


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_figure_desc_included_when_beta_on(tmp_path):
    conn, vs, nb = _figure_desc_fixture(tmp_path)
    svc = RetrievalService(
        conn=conn, vector_store=vs, ollama=FakeGateway(), embedding_model="bge-m3",
        figure_desc_enabled=lambda: True,
    )
    hits = await svc.search(notebook_id=nb.id, query="hi", limit=10)
    assert {h.text for h in hits} == {"本文チャンク", "図の説明チャンク"}


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_figure_desc_included_when_getter_not_wired(tmp_path):
    """getter未配線(既存テスト・他の構築箇所)では従来どおり全件返す。"""
    conn, vs, nb = _figure_desc_fixture(tmp_path)
    svc = RetrievalService(
        conn=conn, vector_store=vs, ollama=FakeGateway(), embedding_model="bge-m3",
    )
    hits = await svc.search(notebook_id=nb.id, query="hi", limit=10)
    assert len(hits) == 2

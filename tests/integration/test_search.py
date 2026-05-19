import pytest

from core.retrieval.search import RetrievalService, RetrievedChunk
from core.storage.database import connect, migrate
from core.storage.notebooks_repo import create_notebook
from core.storage.sources_repo import create_source
from core.storage.chunks_repo import ChunkRecord, insert_chunks
from core.storage.vector_store import ChunkVector, VectorStore

class FakeGateway:
    async def embed(self, *, model: str, text: str) -> list[float]:
        return [1.0, 0.0, 0.0, 0.0]

@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_retrieval_returns_joined_chunks(tmp_path):
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    src = create_source(conn, notebook_id=nb.id, kind="md", title="Doc", content_hash="h")
    chunks = [
        ChunkRecord(id="a"*26, source_id=src.id, notebook_id=nb.id, ord=0,
                    page=1, heading_path="Ch1", text="hello world", token_count=2),
    ]
    insert_chunks(conn, chunks)
    vs = VectorStore(path=tmp_path / "q", dim=4)
    vs.ensure_collection()
    vs.upsert([ChunkVector(
        id="a"*26, vector=[1, 0, 0, 0], notebook_id=nb.id,
        source_id=src.id, source_kind="md", page=1, heading_path="Ch1", ord=0
    )])

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

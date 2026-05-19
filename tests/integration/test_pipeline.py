import pytest
from pathlib import Path

from core.ingestion.pipeline import IngestionPipeline, PipelineDeps
from core.storage.database import connect, migrate
from core.storage.notebooks_repo import create_notebook
from core.storage.sources_repo import SourceStatus, create_source, get_source
from core.storage.vector_store import VectorStore

class FakeGateway:
    async def embed(self, *, model: str, text: str) -> list[float]:
        # 4-dim toy vector
        return [float(len(text)), 0.0, 0.0, 0.0]

@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_pipeline_processes_markdown_end_to_end(tmp_path):
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    src = create_source(
        conn, notebook_id=nb.id, kind="markdown",
        origin="x.md", content_hash="h",
    )

    vs = VectorStore(path=tmp_path / "qdrant", dim=4)
    vs.ensure_collection()

    pipeline = IngestionPipeline(
        deps=PipelineDeps(
            conn=conn,
            vector_store=vs,
            ollama=FakeGateway(),
            embedding_model="bge-m3",
        )
    )
    await pipeline.run(
        source_id=src.id,
        kind="markdown",
        data=b"# Title\n\nSome content here.\n\n## Section\n\nMore content.\n",
    )

    refreshed = get_source(conn, src.id)
    assert refreshed.status == SourceStatus.READY
    assert refreshed.chunk_count and refreshed.chunk_count > 0

    hits = vs.search(query=[1.0, 0, 0, 0], notebook_id=nb.id, limit=5)
    assert len(hits) > 0

@pytest.mark.asyncio
async def test_pipeline_marks_error_on_parse_failure(tmp_path):
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    src = create_source(conn, notebook_id=nb.id, kind="pdf", content_hash="h")
    vs = VectorStore(path=tmp_path / "qdrant", dim=4)
    vs.ensure_collection()
    pipeline = IngestionPipeline(
        deps=PipelineDeps(
            conn=conn, vector_store=vs, ollama=FakeGateway(), embedding_model="bge-m3"
        )
    )
    # corrupted PDF bytes
    await pipeline.run(source_id=src.id, kind="pdf", data=b"not a pdf")
    refreshed = get_source(conn, src.id)
    assert refreshed.status == SourceStatus.ERROR
    assert refreshed.error_msg

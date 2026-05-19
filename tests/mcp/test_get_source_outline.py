from core.mcp.tools.get_source_outline import get_source_outline_tool
from core.storage.chunks_repo import ChunkRecord, insert_chunks
from core.storage.database import connect, migrate
from core.storage.notebooks_repo import create_notebook
from core.storage.sources_repo import SourceStatus, create_source, update_source_status


def test_outline_returns_title_pages_and_headings(tmp_path):
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    src = create_source(
        conn, notebook_id=nb.id, kind="pdf", origin="x.pdf", content_hash="h", title="Doc Title"
    )
    update_source_status(conn, src.id, status=SourceStatus.READY, page_count=2)
    chunks = [
        ChunkRecord(
            id="a" * 26,
            source_id=src.id,
            notebook_id=nb.id,
            ord=0,
            page=1,
            heading_path="Ch1",
            text="x",
            token_count=1,
        ),
        ChunkRecord(
            id="b" * 26,
            source_id=src.id,
            notebook_id=nb.id,
            ord=1,
            page=2,
            heading_path="Ch2",
            text="y",
            token_count=1,
        ),
    ]
    insert_chunks(conn, chunks)
    out = get_source_outline_tool(conn=conn, source_id=src.id)
    assert out["title"] == "Doc Title"
    assert out["kind"] == "pdf"
    assert out["page_count"] == 2
    headings = [h["heading_path"] for h in out["headings"]]
    assert "Ch1" in headings and "Ch2" in headings

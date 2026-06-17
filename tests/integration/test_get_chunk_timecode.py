"""Integration test: GET /api/notebooks/{nb}/sources/{sid}/chunks/{cid}
exposes start_ms, end_ms, speaker for recording chunks.

Mirrors the fixture pattern in tests/integration/test_api/test_sources_api.py:
- monkeypatch NOTEBOOK_OLLAMA_DATA_DIR to tmp_path
- create_app() + TestClient
- NoopPipeline to avoid Ollama dependency
- use app.state.ctx.conn to insert fixtures into the same DB
"""
import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        ctx = c.app.state.ctx

        class NoopPipeline:
            async def run(self, *, source_id, kind, data):
                from core.storage.sources_repo import SourceStatus, update_source_status
                update_source_status(ctx.conn, source_id, status=SourceStatus.READY, chunk_count=0)

        ctx.pipeline = NoopPipeline()
        yield c


def test_get_chunk_exposes_timecode(client):
    # Create notebook via API
    r = client.post("/api/notebooks", json={"name": "N"})
    assert r.status_code == 201
    nb = r.json()["id"]

    # Create a recording source directly in DB (no file upload needed)
    ctx = client.app.state.ctx
    from core.storage.sources_repo import create_source
    src = create_source(
        ctx.conn,
        notebook_id=nb,
        kind="recording",
        origin="interview.mp3",
        content_hash="abc_timecode_test",
    )
    sid = src.id

    # Insert chunk with timecode via chunks_repo
    from core.storage.chunks_repo import ChunkRecord, insert_chunks
    chunk = ChunkRecord(
        id="0" * 26,
        source_id=sid,
        notebook_id=nb,
        ord=0,
        page=None,
        heading_path=None,
        text="test utterance",
        token_count=2,
        start_ms=754000,
        end_ms=758000,
        speaker="相手1",
    )
    insert_chunks(ctx.conn, [chunk])

    # GET the chunk via API
    r = client.get(f"/api/notebooks/{nb}/sources/{sid}/chunks/{chunk.id}")
    assert r.status_code == 200
    body = r.json()

    assert body["start_ms"] == 754000
    assert body["end_ms"] == 758000
    assert body["speaker"] == "相手1"

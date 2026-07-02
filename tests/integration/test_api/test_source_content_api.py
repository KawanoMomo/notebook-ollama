import io

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


def _create_nb(client) -> str:
    return client.post("/api/notebooks", json={"name": "N"}).json()["id"]


def test_content_document_reparses_faithfully(client):
    nb = _create_nb(client)
    md = b"# Title\n\nfirst para.\n\n## Sub\n\nsecond para.\n"
    files = {"file": ("doc.md", io.BytesIO(md), "text/markdown")}
    sid = client.post(f"/api/notebooks/{nb}/sources", files=files).json()["id"]

    r = client.get(f"/api/notebooks/{nb}/sources/{sid}/content")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "document"
    texts = [s["text"] for s in body["sections"]]
    assert any("first para." in t for t in texts)
    assert any("second para." in t for t in texts)
    # heading structure is preserved (joined with " > ")
    assert any(s["heading_path"] and "Sub" in s["heading_path"] for s in body["sections"])


def test_content_recording_returns_ordered_segments(client):
    nb = _create_nb(client)
    ctx = client.app.state.ctx
    from core.storage.chunks_repo import ChunkRecord, insert_chunks
    from core.storage.sources_repo import create_source

    src = create_source(
        ctx.conn, notebook_id=nb, kind="recording",
        origin="talk.mp3", content_hash="rec_content_test",
    )
    sid = src.id
    insert_chunks(ctx.conn, [
        ChunkRecord(id="1" * 26, source_id=sid, notebook_id=nb, ord=1,
                    page=None, heading_path=None, text="second", token_count=1,
                    start_ms=2000, end_ms=3000, speaker="相手1"),
        ChunkRecord(id="0" * 26, source_id=sid, notebook_id=nb, ord=0,
                    page=None, heading_path=None, text="first", token_count=1,
                    start_ms=0, end_ms=1000, speaker="あなた"),
    ])

    r = client.get(f"/api/notebooks/{nb}/sources/{sid}/content")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "recording"
    assert [s["ord"] for s in body["segments"]] == [0, 1]
    assert body["segments"][0] == {
        "ord": 0, "text": "first", "start_ms": 0, "end_ms": 1000, "speaker": "あなた",
    }
    assert body["segments"][1]["speaker"] == "相手1"


def test_content_rejects_source_from_other_notebook(client):
    nb1 = _create_nb(client)
    nb2 = _create_nb(client)
    files = {"file": ("a.md", io.BytesIO(b"# A"), "text/markdown")}
    sid = client.post(f"/api/notebooks/{nb1}/sources", files=files).json()["id"]
    r = client.get(f"/api/notebooks/{nb2}/sources/{sid}/content")
    assert r.status_code == 404

import io

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    # patch the ingestion pipeline to a no-op so we don't need Ollama
    with TestClient(app) as c:
        ctx = c.app.state.ctx

        class NoopPipeline:
            async def run(self, *, source_id, kind, data):
                from core.storage.sources_repo import SourceStatus, update_source_status

                update_source_status(ctx.conn, source_id, status=SourceStatus.READY, chunk_count=0)

        ctx.pipeline = NoopPipeline()
        yield c


def _create_nb(client) -> str:
    r = client.post("/api/notebooks", json={"name": "N"})
    return r.json()["id"]


def test_upload_markdown_source(client):
    nb = _create_nb(client)
    files = {"file": ("hello.md", io.BytesIO(b"# Hello\n\nbody."), "text/markdown")}
    r = client.post(f"/api/notebooks/{nb}/sources", files=files)
    assert r.status_code == 202
    body = r.json()
    assert body["status"] in {"pending", "ready"}


def test_upload_unsupported_kind_returns_400(client):
    nb = _create_nb(client)
    files = {"file": ("hello.bin", io.BytesIO(b"\x00\x01"), "application/octet-stream")}
    r = client.post(f"/api/notebooks/{nb}/sources", files=files)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "ingestion.unsupported_kind"


def test_list_sources(client):
    nb = _create_nb(client)
    files = {"file": ("a.md", io.BytesIO(b"# A"), "text/markdown")}
    client.post(f"/api/notebooks/{nb}/sources", files=files)
    r = client.get(f"/api/notebooks/{nb}/sources")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_delete_source(client):
    nb = _create_nb(client)
    files = {"file": ("a.md", io.BytesIO(b"# A"), "text/markdown")}
    r = client.post(f"/api/notebooks/{nb}/sources", files=files)
    sid = r.json()["id"]
    r = client.delete(f"/api/notebooks/{nb}/sources/{sid}")
    assert r.status_code == 204


def test_retry_source_with_saved_bytes(client):
    nb = _create_nb(client)
    files = {"file": ("hello.md", io.BytesIO(b"# Hello\n\nbody."), "text/markdown")}
    r = client.post(f"/api/notebooks/{nb}/sources", files=files)
    sid = r.json()["id"]
    # mark as error to exercise retry path
    from core.storage.sources_repo import SourceStatus, update_source_status
    ctx = client.app.state.ctx
    update_source_status(ctx.conn, sid, status=SourceStatus.ERROR, error_msg="forced")
    r = client.post(f"/api/notebooks/{nb}/sources/{sid}/retry")
    assert r.status_code == 200
    assert r.json()["status"] in {"pending", "ready"}


def test_retry_source_missing_bytes_returns_400(client, tmp_path):
    nb = _create_nb(client)
    files = {"file": ("hello.md", io.BytesIO(b"# X"), "text/markdown")}
    r = client.post(f"/api/notebooks/{nb}/sources", files=files)
    sid = r.json()["id"]
    # delete the saved bytes manually
    ctx = client.app.state.ctx
    from pathlib import Path
    for p in Path(ctx.config.sources_dir).glob(f"{sid}.*"):
        p.unlink()
    r = client.post(f"/api/notebooks/{nb}/sources/{sid}/retry")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "input.invalid"


def test_get_chunk_returns_chunk_text(client):
    nb = _create_nb(client)
    files = {"file": ("hello.md", io.BytesIO(b"# Hello\n\nbody."), "text/markdown")}
    r = client.post(f"/api/notebooks/{nb}/sources", files=files)
    sid = r.json()["id"]
    # the no-op pipeline created 0 chunks; manually insert a chunk
    ctx = client.app.state.ctx
    from core.storage.chunks_repo import ChunkRecord, insert_chunks
    chunk = ChunkRecord(
        id="0" * 26, source_id=sid, notebook_id=nb,
        ord=0, page=1, heading_path="h", text="hello chunk", token_count=2,
    )
    insert_chunks(ctx.conn, [chunk])
    r = client.get(f"/api/notebooks/{nb}/sources/{sid}/chunks/{chunk.id}")
    assert r.status_code == 200
    assert r.json()["text"] == "hello chunk"

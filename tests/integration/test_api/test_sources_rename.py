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


def _create_nb(client, name="N") -> str:
    r = client.post("/api/notebooks", json={"name": name})
    return r.json()["id"]


def _upload_doc(client, nb) -> str:
    files = {"file": ("hello.md", io.BytesIO(b"# Hello\n\nbody."), "text/markdown")}
    r = client.post(f"/api/notebooks/{nb}/sources", files=files)
    assert r.status_code == 202, r.text
    return r.json()["id"]


def _create_recording(client, nb) -> str:
    from core.storage import sources_repo

    ctx = client.app.state.ctx
    src = sources_repo.create_source(
        ctx.conn, notebook_id=nb, kind="recording", title=None, origin="録音"
    )
    return src.id


def test_rename_recording_returns_updated_title(client):
    nb = _create_nb(client)
    sid = _create_recording(client, nb)
    r = client.patch(
        f"/api/notebooks/{nb}/sources/{sid}", json={"title": "週次定例 RAG 改善"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == sid
    assert body["title"] == "週次定例 RAG 改善"
    # persisted: a fresh GET reflects the new title.
    listed = client.get(f"/api/notebooks/{nb}/sources").json()
    assert any(s["id"] == sid and s["title"] == "週次定例 RAG 改善" for s in listed)


def test_rename_document_source(client):
    nb = _create_nb(client)
    sid = _upload_doc(client, nb)
    r = client.patch(
        f"/api/notebooks/{nb}/sources/{sid}", json={"title": "仕様メモ"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "仕様メモ"


def test_rename_empty_title_returns_400(client):
    nb = _create_nb(client)
    sid = _create_recording(client, nb)
    r = client.patch(f"/api/notebooks/{nb}/sources/{sid}", json={"title": "   "})
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "input.invalid"


def test_rename_cross_notebook_returns_404(client):
    nb_a = _create_nb(client, "A")
    nb_b = _create_nb(client, "B")
    sid = _create_recording(client, nb_a)
    r = client.patch(f"/api/notebooks/{nb_b}/sources/{sid}", json={"title": "x"})
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "storage.not_found"

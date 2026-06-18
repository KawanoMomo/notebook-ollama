"""GET /sources が録音ソースの has_audio を音源ファイルの有無から計算することを検証する。"""

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        yield c


def _create_nb(client) -> str:
    return client.post("/api/notebooks", json={"name": "has_audio"}).json()["id"]


def test_recording_with_audio_reports_has_audio_true(client):
    nb = _create_nb(client)
    ctx = client.app.state.ctx
    from core.storage import sources_repo

    src = sources_repo.create_source(
        ctx.conn, notebook_id=nb, kind="recording", title="rec", origin="録音"
    )
    d = ctx.config.sources_dir / src.id
    d.mkdir(parents=True, exist_ok=True)
    (d / "mic.m4a").write_bytes(b"\x00" * 128)

    rows = client.get(f"/api/notebooks/{nb}/sources").json()
    got = next(r for r in rows if r["id"] == src.id)
    assert got["has_audio"] is True


def test_recording_without_audio_reports_has_audio_false(client):
    nb = _create_nb(client)
    ctx = client.app.state.ctx
    from core.storage import sources_repo

    src = sources_repo.create_source(
        ctx.conn, notebook_id=nb, kind="recording", title="rec", origin="録音"
    )
    (ctx.config.sources_dir / src.id).mkdir(parents=True, exist_ok=True)

    rows = client.get(f"/api/notebooks/{nb}/sources").json()
    got = next(r for r in rows if r["id"] == src.id)
    assert got["has_audio"] is False

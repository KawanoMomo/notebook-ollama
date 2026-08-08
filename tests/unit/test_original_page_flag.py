"""原本ページ表示のベータゲート。"""

import pymupdf
import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.features import get_flag, is_enabled
from core.storage import sources_repo


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        yield c


def _seed(client):
    nb = client.post("/api/notebooks", json={"name": "ゲート"}).json()["id"]
    ctx = client.app.state.ctx
    src = sources_repo.create_source(
        ctx.conn, notebook_id=nb, kind="pdf", title="t", origin="t.pdf"
    )
    ctx.config.sources_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    doc.new_page().insert_textbox(pymupdf.Rect(50, 50, 400, 120), "hello", fontsize=12)
    doc.save(ctx.config.sources_dir / f"{src.id}.pdf")
    doc.close()
    return nb, src.id


def test_flag_is_registered_as_beta_and_off_by_default():
    flag = get_flag("original-page-view")
    assert flag is not None
    assert flag.stage == "beta"
    assert is_enabled("original-page-view", {}) is False


def test_page_endpoint_is_blocked_while_disabled(client):
    nb, sid = _seed(client)
    res = client.get(f"/api/notebooks/{nb}/sources/{sid}/pages/1?dpi=150")
    assert res.status_code == 403


def test_rects_endpoint_is_blocked_while_disabled(client):
    nb, sid = _seed(client)
    res = client.post(
        f"/api/notebooks/{nb}/sources/{sid}/pages/1/rects",
        json={"chunk_id": "c", "quote": "hello", "dpi": 150},
    )
    assert res.status_code == 403


def test_page_endpoint_works_once_enabled(client):
    nb, sid = _seed(client)
    client.put("/api/features/original-page-view", json={"enabled": True})
    res = client.get(f"/api/notebooks/{nb}/sources/{sid}/pages/1?dpi=150")
    assert res.status_code == 200
    assert res.content.startswith(b"\x89PNG")

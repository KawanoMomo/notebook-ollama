"""ソース削除で原本ページ画像キャッシュも消えること。"""

import pymupdf
import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.storage import sources_repo


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        yield c


def _seed(client) -> tuple[str, str]:
    nb = client.post("/api/notebooks", json={"name": "キャッシュ掃除"}).json()["id"]
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


def test_deleting_source_removes_page_cache(client):
    nb, sid = _seed(client)
    assert client.get(f"/api/notebooks/{nb}/sources/{sid}/pages/1?dpi=150").status_code == 200

    ctx = client.app.state.ctx
    cache_dir = ctx.config.data_dir / "cache" / "pages" / sid
    assert cache_dir.exists(), "ページ画像がキャッシュされていない"

    res = client.delete(f"/api/notebooks/{nb}/sources/{sid}")
    assert res.status_code in (200, 204)
    assert not cache_dir.exists(), "ソース削除後もページ画像キャッシュが残っている"

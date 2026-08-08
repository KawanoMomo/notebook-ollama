"""原本ページ画像・矩形エンドポイントの契約。

セットアップは tests/integration/test_api/test_audio_serving_range.py に倣う。
"""

import json

import pymupdf
import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.storage import assets_repo, sources_repo
from core.storage.assets_repo import AssetRecord


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        yield c


def _create_nb(client, name="原本ページテスト") -> str:
    # 原本ページ表示はベータ。既定 OFF なので、契約テストでは有効にしてから叩く。
    client.put("/api/features/original-page-view", json={"enabled": True})
    return client.post("/api/notebooks", json={"name": name}).json()["id"]


def _seed_pdf_source(client, notebook_id: str) -> str:
    """pdf 種別のソース行と、その実体 PDF を作る。"""
    ctx = client.app.state.ctx
    src = sources_repo.create_source(
        ctx.conn, notebook_id=notebook_id, kind="pdf", title="t", origin="t.pdf"
    )
    ctx.config.sources_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for i in range(2):
        page = doc.new_page()
        page.insert_textbox(
            pymupdf.Rect(50, 100, 500, 200),
            f"The process achieves its outcomes on page {i + 1}.",
            fontsize=12,
            fontname="helv",
        )
    doc.save(ctx.config.sources_dir / f"{src.id}.pdf")
    doc.close()
    return src.id


def _seed_text_source(client, notebook_id: str) -> str:
    ctx = client.app.state.ctx
    src = sources_repo.create_source(
        ctx.conn, notebook_id=notebook_id, kind="text", title="t", origin="t.txt"
    )
    return src.id


def _seed_table_asset(client, source_id: str, chunk_id: str) -> None:
    ctx = client.app.state.ctx
    assets_repo.insert_assets(
        ctx.conn,
        [
            AssetRecord(
                id="asset-1",
                source_id=source_id,
                chunk_id=chunk_id,
                kind="table",
                page=1,
                bbox_json=json.dumps([72.0, 144.0, 144.0, 216.0]),
                html="<table></table>",
                md_snippet="| a |",
                image_path=None,
                created_at="2026-08-08T00:00:00Z",
            )
        ],
    )


def test_page_png_returns_image(client):
    nb = _create_nb(client)
    sid = _seed_pdf_source(client, nb)
    res = client.get(f"/api/notebooks/{nb}/sources/{sid}/pages/1?dpi=150")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.content.startswith(b"\x89PNG")


def test_page_png_rejects_dpi_outside_allowlist(client):
    nb = _create_nb(client)
    sid = _seed_pdf_source(client, nb)
    res = client.get(f"/api/notebooks/{nb}/sources/{sid}/pages/1?dpi=1200")
    assert res.status_code == 400


def test_page_png_404_for_out_of_range_page(client):
    nb = _create_nb(client)
    sid = _seed_pdf_source(client, nb)
    res = client.get(f"/api/notebooks/{nb}/sources/{sid}/pages/999?dpi=150")
    assert res.status_code == 404


def test_page_png_404_for_non_pdf_source(client):
    nb = _create_nb(client)
    sid = _seed_text_source(client, nb)
    res = client.get(f"/api/notebooks/{nb}/sources/{sid}/pages/1?dpi=150")
    assert res.status_code == 404


def test_rects_uses_asset_bbox_when_chunk_has_asset(client):
    nb = _create_nb(client)
    sid = _seed_pdf_source(client, nb)
    _seed_table_asset(client, sid, "chunk-with-table")
    res = client.post(
        f"/api/notebooks/{nb}/sources/{sid}/pages/1/rects",
        json={"chunk_id": "chunk-with-table", "quote": "この文字列は原本に存在しない", "dpi": 150},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["source"] == "asset"
    assert len(body["rects"]) == 1
    assert body["rects"][0]["x"] == pytest.approx(150.0)


def test_rects_falls_back_to_quote_search(client):
    nb = _create_nb(client)
    sid = _seed_pdf_source(client, nb)
    res = client.post(
        f"/api/notebooks/{nb}/sources/{sid}/pages/1/rects",
        json={"chunk_id": "no-such-chunk", "quote": "achieves its outcomes", "dpi": 150},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["source"] == "quote"
    assert len(body["rects"]) >= 1


def test_rects_reports_none_when_nothing_matches(client):
    nb = _create_nb(client)
    sid = _seed_pdf_source(client, nb)
    res = client.post(
        f"/api/notebooks/{nb}/sources/{sid}/pages/1/rects",
        json={"chunk_id": "no-such-chunk", "quote": "zzz qqq", "dpi": 150},
    )
    assert res.status_code == 200
    assert res.json() == {"rects": [], "source": "none"}

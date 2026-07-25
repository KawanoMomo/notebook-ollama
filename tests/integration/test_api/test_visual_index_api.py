from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        yield c


def _nb(client) -> str:
    return client.post("/api/notebooks", json={"name": "N"}).json()["id"]


def _beta(client, on=True):
    client.put("/api/features/table-figure-rag", json={"enabled": on})


def test_all_endpoints_403_when_beta_off(client):
    nb = _nb(client)
    _beta(client, False)
    assert client.post(f"/api/notebooks/{nb}/visual-index").status_code == 403
    assert client.get(f"/api/notebooks/{nb}/visual-index").status_code == 403
    assert client.delete(f"/api/notebooks/{nb}/visual-index").status_code == 403


def test_status_reports_unbuilt_and_extra_flag(client):
    nb = _nb(client)
    _beta(client)
    res = client.get(f"/api/notebooks/{nb}/visual-index")
    assert res.status_code == 200
    body = res.json()
    assert body["built"] is False and body["building"] is False
    assert isinstance(body["extra_available"], bool)


def test_build_503_when_extra_missing(client, monkeypatch):
    import apps.api.routers.visual_index as vi_mod

    monkeypatch.setattr(vi_mod, "visual_extra_available", lambda: False)
    nb = _nb(client)
    _beta(client)
    res = client.post(f"/api/notebooks/{nb}/visual-index")
    assert res.status_code == 503
    assert "uv sync --extra visual" in res.text


def test_build_202_and_status_built_with_fake_encoder(client, monkeypatch):
    import apps.api.routers.visual_index as vi_mod

    class FakeEncoder:
        async def embed_image(self, *, png: bytes) -> list[float]:
            return [1.0, 0.0, 0.0, 0.0]

        async def embed_text(self, *, text: str) -> list[float]:
            return [1.0, 0.0, 0.0, 0.0]

        def unload(self) -> None:
            pass

    monkeypatch.setattr(vi_mod, "visual_extra_available", lambda: True)
    ctx = client.app.state.ctx
    ctx.visual_encoder = FakeEncoder()
    nb = _nb(client)
    _beta(client)
    res = client.post(f"/api/notebooks/{nb}/visual-index")
    assert res.status_code == 202
    # PDFソースが無いので即完了・built=Falseのまま(indexed 0件ではmetaを書かない)
    status = client.get(f"/api/notebooks/{nb}/visual-index").json()
    assert status["built"] is False


def test_delete_removes_meta(client, monkeypatch):
    import apps.api.routers.visual_index as vi_mod
    from core.storage.visual_index_repo import VisualIndexMeta, upsert_meta

    monkeypatch.setattr(vi_mod, "visual_extra_available", lambda: True)
    nb = _nb(client)
    _beta(client)
    ctx = client.app.state.ctx
    upsert_meta(ctx.conn, VisualIndexMeta(notebook_id=nb, embedding_model="m", built_at="t"))
    assert client.get(f"/api/notebooks/{nb}/visual-index").json()["built"] is True
    res = client.delete(f"/api/notebooks/{nb}/visual-index")
    assert res.status_code == 204
    assert client.get(f"/api/notebooks/{nb}/visual-index").json()["built"] is False


def test_source_reingest_clears_visual_rows(client, monkeypatch):
    """再取込したソースは視覚索引から外れ、pending としてカウントされる。"""
    # ソース作成が重い(実PDF取込)ため、visual_index_sources への直接insert +
    # _clear_source_derived_data 直接呼び出しで検証する
    from apps.api.routers.sources import _clear_source_derived_data
    from core.storage.visual_index_repo import (
        list_indexed_source_ids,
        mark_source_indexed,
    )

    nb = _nb(client)
    _beta(client)
    ctx = client.app.state.ctx
    mark_source_indexed(ctx.conn, notebook_id=nb, source_id="sX", page_count=2, built_at="t")
    _clear_source_derived_data(ctx, "sX")
    assert list_indexed_source_ids(ctx.conn, nb) == set()

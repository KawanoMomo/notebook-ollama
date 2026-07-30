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


def _install_fake_encoder(client, monkeypatch) -> None:
    """既存テストの「ctx.visual_encoder に FakeEncoder を直代入する」手口のヘルパ版。"""
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


def test_all_endpoints_403_when_beta_off(client):
    nb = _nb(client)
    _beta(client, False)
    assert client.get(f"/api/notebooks/{nb}/visual-index").status_code == 403
    assert client.post(f"/api/notebooks/{nb}/visual-index?unit=tile").status_code == 403
    assert client.delete(f"/api/notebooks/{nb}/visual-index?unit=tile").status_code == 403


def test_status_returns_both_units(client):
    nb = _nb(client)
    _beta(client, True)
    body = client.get(f"/api/notebooks/{nb}/visual-index").json()
    assert set(body["units"]) == {"page", "tile"}
    assert body["units"]["page"]["built"] is False
    assert body["units"]["tile"]["built"] is False
    assert isinstance(body["extra_available"], bool)
    assert body["index_unit"] == "page"
    assert body["search_strategy"] == "hybrid_rrf"


def test_build_503_when_extra_missing(client, monkeypatch):
    import apps.api.routers.visual_index as vi_mod

    monkeypatch.setattr(vi_mod, "visual_extra_available", lambda: False)
    nb = _nb(client)
    _beta(client)
    res = client.post(f"/api/notebooks/{nb}/visual-index")
    assert res.status_code == 503
    assert "uv sync --extra visual" in res.text


def test_build_rejects_unknown_unit(client):
    nb = _nb(client)
    _beta(client, True)
    res = client.post(f"/api/notebooks/{nb}/visual-index?unit=region")
    assert res.status_code == 422


def test_build_defaults_to_page_unit(client, monkeypatch):
    """unit を省略した既存クライアントの呼び出しは page 索引を構築する。"""
    nb = _nb(client)
    _beta(client, True)
    _install_fake_encoder(client, monkeypatch)
    res = client.post(f"/api/notebooks/{nb}/visual-index")
    assert res.status_code == 202
    assert res.json()["unit"] == "page"


def test_build_tile_unit_accepted(client, monkeypatch):
    nb = _nb(client)
    _beta(client, True)
    _install_fake_encoder(client, monkeypatch)
    res = client.post(f"/api/notebooks/{nb}/visual-index?unit=tile")
    assert res.status_code == 202
    assert res.json() == {"status": "accepted", "unit": "tile"}


def test_building_one_unit_does_not_block_the_other(client, monkeypatch):
    from core.visual.index_builder import mark_building, unmark_building

    nb = _nb(client)
    _beta(client, True)
    _install_fake_encoder(client, monkeypatch)
    mark_building(nb, "tile")
    try:
        # tile は二重起動ガードに掛かる
        res_tile = client.post(f"/api/notebooks/{nb}/visual-index?unit=tile")
        assert res_tile.json()["status"] == "already_building"
        # page は独立して受理される
        res_page = client.post(f"/api/notebooks/{nb}/visual-index?unit=page")
        assert res_page.json()["status"] == "accepted"
    finally:
        unmark_building(nb, "tile")


def test_delete_removes_only_the_requested_unit(client):
    nb = _nb(client)
    _beta(client, True)
    ctx = client.app.state.ctx
    from core.storage.visual_index_repo import VisualIndexMeta, get_meta, upsert_meta

    upsert_meta(ctx.conn, VisualIndexMeta(nb, "m", "t1"))
    upsert_meta(ctx.conn, VisualIndexMeta(nb, "m", "t2", unit="tile"))

    assert client.delete(f"/api/notebooks/{nb}/visual-index?unit=tile").status_code == 204
    assert get_meta(ctx.conn, nb, "page") is not None
    assert get_meta(ctx.conn, nb, "tile") is None


def test_source_reingest_clears_visual_rows(client):
    """再取込したソースは視覚索引(両単位)から外れ、pending としてカウントされる。"""
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
    mark_source_indexed(
        ctx.conn, notebook_id=nb, source_id="sX", page_count=6, built_at="t", unit="tile"
    )
    _clear_source_derived_data(ctx, "sX")
    assert list_indexed_source_ids(ctx.conn, nb, "page") == set()
    assert list_indexed_source_ids(ctx.conn, nb, "tile") == set()

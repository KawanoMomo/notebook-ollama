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


def _install_always_failing_encoder(client, monkeypatch) -> None:
    """全単位の embed_image が必ず失敗するエンコーダ(不具合A回帰テスト用)。

    実機では GPU の cuDNN 不整合により全ページが失敗したが、build() は
    単位ごとの失敗を握り潰して例外を投げない(部分成功の設計)ため、
    _run_build 側が例外の有無だけで成否判定すると「1件も索引できて
    いないのに成功トースト」になる。
    """
    import apps.api.routers.visual_index as vi_mod

    class AlwaysFailingEncoder:
        async def embed_image(self, *, png: bytes) -> list[float]:
            raise RuntimeError("boom: simulated cuDNN mismatch")

        async def embed_text(self, *, text: str) -> list[float]:
            return [1.0, 0.0, 0.0, 0.0]

        def unload(self) -> None:
            pass

    monkeypatch.setattr(vi_mod, "visual_extra_available", lambda: True)
    ctx = client.app.state.ctx
    ctx.visual_encoder = AlwaysFailingEncoder()


def _make_ready_pdf_source(ctx, nb: str, *, sid_hint: str = "h1") -> str:
    """READY な PDF ソースを1本作る。中身は _render_pages をモックするため
    ダミーバイト列でよい(pdf_path.exists() の判定にのみ使われる)。"""
    from core.storage.sources_repo import SourceStatus, create_source, update_source_status

    src = create_source(
        ctx.conn, notebook_id=nb, kind="pdf", origin="t.pdf", content_hash=sid_hint
    )
    (ctx.config.sources_dir / f"{src.id}.pdf").write_bytes(b"dummy-pdf-bytes")
    update_source_status(ctx.conn, src.id, status=SourceStatus.READY)
    return src.id


def test_all_pages_failing_publishes_error_not_complete(client, monkeypatch):
    """回帰テスト(実機検証15b・不具合A): 全ページ失敗
    (indexed_pages=0 かつ skipped_pages>0)でも visual_index_complete を
    publish してはいけない。「complete が出ないこと」ではなく
    「error が出ること」を積極的に検証する。"""
    import core.visual.index_builder as builder_mod

    # ページレンダリングは正常、埋め込みだけが全滅する状況を作る
    # (real PyMuPDF に依存しないよう _render_pages をモックする)。
    monkeypatch.setattr(
        builder_mod.VisualIndexBuilder,
        "_render_pages",
        lambda self, pdf_path: [b"fake-page-png"],
    )

    nb = _nb(client)
    _beta(client, True)
    _install_always_failing_encoder(client, monkeypatch)
    ctx = client.app.state.ctx
    _make_ready_pdf_source(ctx, nb)

    published: list[dict] = []

    async def fake_publish(channel: str, payload: dict) -> None:
        published.append(payload)

    monkeypatch.setattr(ctx.sse, "publish", fake_publish)

    res = client.post(f"/api/notebooks/{nb}/visual-index?unit=page")
    assert res.status_code == 202

    terminal = [
        p for p in published
        if p["type"] in ("visual_index_complete", "visual_index_error")
    ]
    assert len(terminal) == 1, published
    assert terminal[0]["type"] == "visual_index_error"
    assert terminal[0]["indexed_pages"] == 0
    assert terminal[0]["skipped_pages"] == 1


def test_render_failure_on_all_sources_publishes_error_not_complete(client, monkeypatch):
    """回帰テスト(レビュー指摘・不具合A残存ケース): PDFファイルが sources_dir から
    欠落している(実運用ではソース削除漏れ・破損PDFでPyMuPDFが開けない等で起こりうる)と、
    ビルダはそのソースを pages_by_source に一切登録せずページループごと丸ごとスキップする
    ため、indexed_pages も skipped_pages も増えない。skipped_pages==0 だけを「対象なし」の
    代理指標にすると、この経路で全滅していても visual_index_complete が出てしまう
    (target_sources 基準の判定でこの抜け道を塞ぐ)。"""
    from core.storage.sources_repo import SourceStatus, create_source, update_source_status

    nb = _nb(client)
    _beta(client, True)
    _install_fake_encoder(client, monkeypatch)
    ctx = client.app.state.ctx

    # READY な PDF ソースは作るが実ファイルは書かない
    # → pdf_path.exists() が False になり、レンダリングにすら到達せずスキップされる。
    src = create_source(
        ctx.conn, notebook_id=nb, kind="pdf", origin="missing.pdf", content_hash="hmiss"
    )
    update_source_status(ctx.conn, src.id, status=SourceStatus.READY)

    published: list[dict] = []

    async def fake_publish(channel: str, payload: dict) -> None:
        published.append(payload)

    monkeypatch.setattr(ctx.sse, "publish", fake_publish)

    res = client.post(f"/api/notebooks/{nb}/visual-index?unit=page")
    assert res.status_code == 202

    terminal = [
        p for p in published
        if p["type"] in ("visual_index_complete", "visual_index_error")
    ]
    assert len(terminal) == 1, published
    assert terminal[0]["type"] == "visual_index_error"
    assert terminal[0]["indexed_pages"] == 0
    assert terminal[0]["skipped_pages"] == 0


def test_no_target_pdf_sources_publishes_noop(client, monkeypatch):
    """最終レビュー I3: 対象PDFソースが1本も無い
    ノートブックでの build は、「何もしなかった」のであって「完了」ではない。
    以前は visual_index_complete
    を publish していたが、これはタイル格子(tile_rows/cols/overlap)を変えて
    再構築したユーザーが「1タイルも作り直されていない」ことに気付けず、成功
    したと誤認する経路と同一の判定(target_sources==0)なので、この境界も
    visual_index_noop に揃える。"""
    nb = _nb(client)
    _beta(client, True)
    _install_fake_encoder(client, monkeypatch)
    ctx = client.app.state.ctx

    published: list[dict] = []

    async def fake_publish(channel: str, payload: dict) -> None:
        published.append(payload)

    monkeypatch.setattr(ctx.sse, "publish", fake_publish)

    res = client.post(f"/api/notebooks/{nb}/visual-index?unit=page")
    assert res.status_code == 202

    terminal = [
        p for p in published
        if p["type"] in ("visual_index_complete", "visual_index_error", "visual_index_noop")
    ]
    assert len(terminal) == 1, published
    assert terminal[0]["type"] == "visual_index_noop"
    assert terminal[0]["indexed_pages"] == 0
    assert terminal[0]["skipped_pages"] == 0


def test_all_sources_already_indexed_publishes_noop(client, monkeypatch):
    """最終レビュー I3 の本題: PDFソースは存在するが、全て既に索引済み(タイル
    格子等のパラメータだけを変えて再構築を試みたケースを模す)だと targets が
    空になり、1タイルも作り直されないまま無言で visual_index_complete が出て
    いた。「対象が0件でした」と分かる別の type(visual_index_noop)を publish
    することを検証する。"""
    nb = _nb(client)
    _beta(client, True)
    _install_fake_encoder(client, monkeypatch)
    ctx = client.app.state.ctx
    src_id = _make_ready_pdf_source(ctx, nb)

    from core.storage.visual_index_repo import mark_source_indexed

    mark_source_indexed(
        ctx.conn, notebook_id=nb, source_id=src_id, page_count=1, built_at="t", unit="page",
    )

    published: list[dict] = []

    async def fake_publish(channel: str, payload: dict) -> None:
        published.append(payload)

    monkeypatch.setattr(ctx.sse, "publish", fake_publish)

    res = client.post(f"/api/notebooks/{nb}/visual-index?unit=page")
    assert res.status_code == 202

    terminal = [
        p for p in published
        if p["type"] in ("visual_index_complete", "visual_index_error", "visual_index_noop")
    ]
    assert len(terminal) == 1, published
    assert terminal[0]["type"] == "visual_index_noop"
    assert terminal[0]["indexed_pages"] == 0
    assert terminal[0]["skipped_pages"] == 0


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

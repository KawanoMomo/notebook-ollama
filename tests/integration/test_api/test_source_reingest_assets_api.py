"""Task 8: reingest / assets API のベータゲート・ディスパッチ・共通クリーンアップ。

実 Ollama やパース処理は不要な層なので ctx.pipeline を calls 記録用フェイクに
差し替える(パイプライン内部のアセット抽出・紐付けは tests/integration/test_ingest_assets.py 側で検証)。
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.storage import sources_repo
from core.storage.assets_repo import AssetRecord, insert_assets, list_assets_for_source
from core.storage.chunks_repo import ChunkRecord, insert_chunks, list_chunks_for_source


class _RecordingPipeline:
    def __init__(self, ctx):
        self.calls: list[dict] = []
        self._ctx = ctx

    async def run(self, *, source_id, kind, data):
        self.calls.append({"source_id": source_id, "kind": kind, "data": data})
        from core.storage.sources_repo import SourceStatus, update_source_status

        update_source_status(self._ctx.conn, source_id, status=SourceStatus.READY, chunk_count=0)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        ctx = c.app.state.ctx
        ctx.pipeline = _RecordingPipeline(ctx)
        yield c


def _create_nb(client) -> str:
    return client.post("/api/notebooks", json={"name": "N"}).json()["id"]


def _enable_beta(client, enabled: bool) -> None:
    client.put("/api/features/table-figure-rag", json={"enabled": enabled})


def _upload_pdf(client, nb) -> str:
    files = {"file": ("t.pdf", io.BytesIO(b"%PDF-1.4\n%fake"), "application/pdf")}
    r = client.post(f"/api/notebooks/{nb}/sources", files=files)
    assert r.status_code == 202, r.text
    return r.json()["id"]


def _seed_asset(ctx, *, source_id: str, chunk_id: str) -> None:
    insert_assets(
        ctx.conn,
        [
            AssetRecord(
                id="asset-1",
                source_id=source_id,
                chunk_id=chunk_id,
                kind="table",
                page=1,
                bbox_json="[0,0,1,1]",
                html="<table></table>",
                md_snippet="| a | b |",
                image_path=None,
                created_at="2026-07-20T00:00:00+00:00",
            )
        ],
    )


# --- ベータゲート ---------------------------------------------------------


def test_list_assets_403_when_beta_off(client):
    nb = _create_nb(client)
    sid = _upload_pdf(client, nb)
    _enable_beta(client, False)
    r = client.get(f"/api/notebooks/{nb}/sources/{sid}/assets")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "feature.disabled"


def test_reingest_403_when_beta_off(client):
    nb = _create_nb(client)
    sid = _upload_pdf(client, nb)
    _enable_beta(client, False)
    r = client.post(f"/api/notebooks/{nb}/sources/{sid}/reingest")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "feature.disabled"


def test_list_assets_200_when_beta_on(client):
    nb = _create_nb(client)
    sid = _upload_pdf(client, nb)
    ctx = client.app.state.ctx
    chunk = ChunkRecord(
        id="c" * 26, source_id=sid, notebook_id=nb,
        ord=0, page=1, heading_path=None, text="| a | b |", token_count=3,
    )
    insert_chunks(ctx.conn, [chunk])
    _seed_asset(ctx, source_id=sid, chunk_id=chunk.id)
    _enable_beta(client, True)

    r = client.get(f"/api/notebooks/{nb}/sources/{sid}/assets")
    assert r.status_code == 200, r.text
    assets = r.json()["assets"]
    assert len(assets) == 1
    assert assets[0]["kind"] == "table"
    assert assets[0]["chunk_id"] == chunk.id


def test_list_assets_404_cross_notebook(client):
    nb_a = _create_nb(client)
    nb_b = _create_nb(client)
    sid = _upload_pdf(client, nb_a)
    _enable_beta(client, True)
    r = client.get(f"/api/notebooks/{nb_b}/sources/{sid}/assets")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "storage.not_found"


# --- reingest ---------------------------------------------------------


def test_reingest_202_dispatches_pipeline_and_clears_derived_data(client):
    nb = _create_nb(client)
    sid = _upload_pdf(client, nb)
    ctx = client.app.state.ctx

    chunk = ChunkRecord(
        id="c" * 26, source_id=sid, notebook_id=nb,
        ord=0, page=1, heading_path=None, text="| a | b |", token_count=3,
    )
    insert_chunks(ctx.conn, [chunk])
    _seed_asset(ctx, source_id=sid, chunk_id=chunk.id)
    asset_dir = ctx.config.assets_dir / sid
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / "asset-1.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    _enable_beta(client, True)
    r = client.post(f"/api/notebooks/{nb}/sources/{sid}/reingest")
    assert r.status_code == 202, r.text
    assert r.json() == {"status": "accepted"}

    # 旧チャンク・アセット(sqlite行 + PNGディレクトリ)がクリアされている
    assert list_chunks_for_source(ctx.conn, sid) == []
    assert list_assets_for_source(ctx.conn, sid) == []
    assert not asset_dir.exists()

    # パイプラインが再ディスパッチされている(TestClient は background task を
    # レスポンス送出前に同期実行するため、ここで既に呼ばれている)。
    # calls[0] は upload 時の初回ディスパッチ、calls[1] が reingest 分。
    pipeline = ctx.pipeline
    assert len(pipeline.calls) == 2
    assert pipeline.calls[1]["source_id"] == sid
    assert pipeline.calls[1]["kind"] == "pdf"


def test_reingest_404_cross_notebook(client):
    nb_a = _create_nb(client)
    nb_b = _create_nb(client)
    sid = _upload_pdf(client, nb_a)
    _enable_beta(client, True)
    r = client.post(f"/api/notebooks/{nb_b}/sources/{sid}/reingest")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "storage.not_found"


@pytest.mark.parametrize("busy", ["parsing", "chunking", "embedding"])
def test_reingest_409_while_processing(client, busy):
    nb = _create_nb(client)
    sid = _upload_pdf(client, nb)
    ctx = client.app.state.ctx
    calls_before = list(ctx.pipeline.calls)  # upload 時の初回ディスパッチ分
    sources_repo.update_source_status(ctx.conn, sid, status=sources_repo.SourceStatus(busy))
    _enable_beta(client, True)

    r = client.post(f"/api/notebooks/{nb}/sources/{sid}/reingest")
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "storage.conflict"
    assert ctx.pipeline.calls == calls_before  # 追加ディスパッチされていない


def test_reingest_400_when_original_file_missing(client, tmp_path):
    nb = _create_nb(client)
    sid = _upload_pdf(client, nb)
    ctx = client.app.state.ctx
    from pathlib import Path

    for p in Path(ctx.config.sources_dir).glob(f"{sid}.*"):
        p.unlink()
    _enable_beta(client, True)

    r = client.post(f"/api/notebooks/{nb}/sources/{sid}/reingest")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "input.invalid"


# --- retry_source: 既存の挙動が維持されている(アセットクリーンアップが副作用として追加) ---


def test_retry_source_still_works_and_clears_assets(client):
    nb = _create_nb(client)
    sid = _upload_pdf(client, nb)
    ctx = client.app.state.ctx
    _seed_asset(ctx, source_id=sid, chunk_id=None)
    asset_dir = ctx.config.assets_dir / sid
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / "asset-1.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    from core.storage.sources_repo import SourceStatus, update_source_status
    update_source_status(ctx.conn, sid, status=SourceStatus.ERROR, error_msg="forced")

    r = client.post(f"/api/notebooks/{nb}/sources/{sid}/retry")
    assert r.status_code == 200, r.text
    assert r.json()["status"] in {"pending", "ready"}
    assert list_assets_for_source(ctx.conn, sid) == []
    assert not asset_dir.exists()

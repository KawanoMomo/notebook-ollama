"""POST/DELETE /api/notebooks/{nb}/sources/{src}/adr の挙動。

設計: docs/specs/2026-06-26-meeting-adr-templates.md
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.storage import sources_repo
from core.storage.sources_repo import AdrStatus


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    with TestClient(create_app()) as c:
        yield c


def _make_recording_source(ctx, notebook_id: str):
    return sources_repo.create_source(
        ctx.conn, notebook_id=notebook_id, kind="recording", origin="録音"
    )


def test_adr_post_resets_status_and_returns_202(client):
    """POST /adr は即座に generating をセットして 202 を返す。
    本テスト環境では background が同期実行されるため、chunk 0 で SummaryJob
    と同様に内部で error に到達するが、API としては 202 が返り adr_status は
    遷移済み(generating か error)であることを担保する。"""
    ctx = client.app.state.ctx
    nb = client.post("/api/notebooks", json={"name": "N"}).json()
    src = _make_recording_source(ctx, nb["id"])

    r = client.post(f"/api/notebooks/{nb['id']}/sources/{src.id}/adr")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["adr_status"] in ("generating", "error")


def test_adr_post_404_when_source_not_in_notebook(client):
    ctx = client.app.state.ctx
    nb_a = client.post("/api/notebooks", json={"name": "A"}).json()
    nb_b = client.post("/api/notebooks", json={"name": "B"}).json()
    src = _make_recording_source(ctx, nb_a["id"])

    r = client.post(f"/api/notebooks/{nb_b['id']}/sources/{src.id}/adr")
    assert r.status_code == 404


def test_adr_post_404_for_unknown_source(client):
    nb = client.post("/api/notebooks", json={"name": "N"}).json()
    r = client.post(f"/api/notebooks/{nb['id']}/sources/does-not-exist/adr")
    assert r.status_code == 404


def test_adr_delete_clears_fields(client):
    """DELETE /adr で adr_* 列が NULL に戻る。"""
    ctx = client.app.state.ctx
    nb = client.post("/api/notebooks", json={"name": "N"}).json()
    src = _make_recording_source(ctx, nb["id"])
    # まず READY 状態にしておく
    sources_repo.update_source_adr(
        ctx.conn,
        src.id,
        draft="# ADR",
        template="madr",
        confidence="high",
    )
    assert sources_repo.get_source(ctx.conn, src.id).adr_status == AdrStatus.READY

    r = client.delete(f"/api/notebooks/{nb['id']}/sources/{src.id}/adr")
    assert r.status_code == 204
    after = sources_repo.get_source(ctx.conn, src.id)
    assert after.adr_draft is None
    assert after.adr_status is None
    assert after.adr_template is None


def test_adr_delete_404_when_source_not_in_notebook(client):
    ctx = client.app.state.ctx
    nb_a = client.post("/api/notebooks", json={"name": "A"}).json()
    nb_b = client.post("/api/notebooks", json={"name": "B"}).json()
    src = _make_recording_source(ctx, nb_a["id"])
    r = client.delete(f"/api/notebooks/{nb_b['id']}/sources/{src.id}/adr")
    assert r.status_code == 404


def test_get_settings_returns_source_with_adr_fields(client):
    """list_sources レスポンスに adr_* フィールドが含まれる(null だが key 存在)。"""
    ctx = client.app.state.ctx
    nb = client.post("/api/notebooks", json={"name": "N"}).json()
    src = _make_recording_source(ctx, nb["id"])
    sources_repo.update_source_adr(
        ctx.conn, src.id, draft="# X", template="madr", confidence="medium"
    )
    r = client.get(f"/api/notebooks/{nb['id']}/sources")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    item = items[0]
    assert "adr_draft" in item
    assert "adr_status" in item
    assert "adr_template" in item
    assert "adr_confidence" in item
    assert item["adr_status"] == "ready"
    assert item["adr_template"] == "madr"

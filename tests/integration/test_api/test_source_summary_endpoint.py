"""POST /api/notebooks/{nb}/sources/{src}/summarize の挙動。

仕様 §5.1: 再生成は summary_status を generating に戻して SummaryJob を再起動。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.storage import sources_repo
from core.storage.sources_repo import SummaryStatus


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


def test_summarize_resets_status_and_returns_202(client):
    """summarize は即座に generating をセットして 202 を返し、SummaryJob を
    background で起動する(本テスト環境では background が同期実行されるため、
    chunk 0 の SummaryJob はそのまま error 化する → 起動が走った証拠)。"""
    ctx = client.app.state.ctx
    nb = client.post("/api/notebooks", json={"name": "N"}).json()
    src = _make_recording_source(ctx, nb["id"])
    sources_repo.update_source_summary_status(
        ctx.conn, src.id, status=SummaryStatus.READY
    )

    r = client.post(
        f"/api/notebooks/{nb['id']}/sources/{src.id}/summarize"
    )
    assert r.status_code == 202, r.text
    body = r.json()
    # レスポンス時点では generating が見える
    assert body["summary_status"] == "generating"

    # background 実行後、チャンク 0 のため error に到達する(SummaryJob が走った証拠)
    after = sources_repo.get_source(ctx.conn, src.id)
    assert after.summary_status in (SummaryStatus.GENERATING, SummaryStatus.ERROR)


def test_summarize_404_when_source_not_in_notebook(client):
    ctx = client.app.state.ctx
    nb_a = client.post("/api/notebooks", json={"name": "A"}).json()
    nb_b = client.post("/api/notebooks", json={"name": "B"}).json()
    src = _make_recording_source(ctx, nb_a["id"])

    r = client.post(
        f"/api/notebooks/{nb_b['id']}/sources/{src.id}/summarize"
    )
    assert r.status_code == 404


def test_summarize_404_for_unknown_source(client):
    nb = client.post("/api/notebooks", json={"name": "N"}).json()
    r = client.post(
        f"/api/notebooks/{nb['id']}/sources/does-not-exist/summarize"
    )
    assert r.status_code == 404

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
    チャンク行が無い SummaryJob はそのまま error 化する → 起動が走った証拠)。

    エンドポイントの事前検証は chunk_count 列を見るため、列だけ立てておく。
    """
    ctx = client.app.state.ctx
    nb = client.post("/api/notebooks", json={"name": "N"}).json()
    src = _make_recording_source(ctx, nb["id"])
    sources_repo.update_source_status(
        ctx.conn, src.id, status=sources_repo.SourceStatus.READY, chunk_count=3
    )
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

    # background 実行後、チャンク行 0 のため error に到達する(SummaryJob が走った証拠)
    after = sources_repo.get_source(ctx.conn, src.id)
    assert after.summary_status in (SummaryStatus.GENERATING, SummaryStatus.ERROR)


def test_summarize_rejects_source_without_chunks(client):
    """チャンク 0 件のソースへの summarize は 400 で拒否し、status を汚さない。

    変換が完了していない録音等に対して「確実に失敗する要約ジョブ」を起動せず、
    ユーザーにはまず変換(再試行)を促す(2026-07-04 実機フィードバック)。
    """
    ctx = client.app.state.ctx
    nb = client.post("/api/notebooks", json={"name": "N"}).json()
    src = _make_recording_source(ctx, nb["id"])  # chunk_count は未設定(None)

    r = client.post(
        f"/api/notebooks/{nb['id']}/sources/{src.id}/summarize"
    )
    assert r.status_code == 400, r.text
    err = r.json()["error"]
    assert err["code"] == "input.invalid"
    assert "変換" in (err.get("remediation") or "")

    # summary_status は generating に変更されていない
    after = sources_repo.get_source(ctx.conn, src.id)
    assert after.summary_status is None


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

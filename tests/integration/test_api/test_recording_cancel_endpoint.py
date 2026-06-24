"""POST /api/notebooks/{nb}/recordings/{sid}/cancel の統合テスト。

進行中変換に停止を要求し、処理中(parsing/chunking/embedding)なら即座に
status=error("変換を停止しました") へ反映する。READY/ERROR は触らない。
パイプラインへ request_cancel が伝わること。実モデルはロードしない。
"""

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.storage import sources_repo


class _FakePipeline:
    def __init__(self):
        self.cancelled: list[str] = []

    def request_cancel(self, source_id: str) -> None:
        self.cancelled.append(source_id)

    async def run(self, **kwargs):
        pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        yield c


def _nb(client) -> str:
    return client.post("/api/notebooks", json={"name": "cancel"}).json()["id"]


def _seed_recording(client, nb, status):
    ctx = client.app.state.ctx
    src = sources_repo.create_source(
        ctx.conn, notebook_id=nb, kind="recording", title="rec", origin="録音"
    )
    sources_repo.update_source_status(ctx.conn, src.id, status=status)
    return src.id


def test_cancel_requests_pipeline_cancel_and_errors_when_processing(client):
    nb = _nb(client)
    fake = _FakePipeline()
    client.app.state.ctx.recording_pipeline = fake
    src_id = _seed_recording(client, nb, sources_repo.SourceStatus.EMBEDDING)

    r = client.post(f"/api/notebooks/{nb}/recordings/{src_id}/cancel")
    assert r.status_code == 200, r.text
    assert r.json()["cancelled"] is True
    assert fake.cancelled == [src_id]

    src = sources_repo.get_source(client.app.state.ctx.conn, src_id)
    assert src.status == sources_repo.SourceStatus.ERROR
    assert "停止" in (src.error_msg or "")


def test_cancel_on_ready_keeps_status(client):
    nb = _nb(client)
    fake = _FakePipeline()
    client.app.state.ctx.recording_pipeline = fake
    src_id = _seed_recording(client, nb, sources_repo.SourceStatus.READY)

    r = client.post(f"/api/notebooks/{nb}/recordings/{src_id}/cancel")
    assert r.status_code == 200, r.text
    assert fake.cancelled == [src_id]
    src = sources_repo.get_source(client.app.state.ctx.conn, src_id)
    assert src.status == sources_repo.SourceStatus.READY  # 完了済みは触らない


def test_cancel_rejects_non_recording(client):
    nb = _nb(client)
    client.app.state.ctx.recording_pipeline = _FakePipeline()
    ctx = client.app.state.ctx
    doc = sources_repo.create_source(
        ctx.conn, notebook_id=nb, kind="pdf", title="doc", origin="a.pdf"
    )
    r = client.post(f"/api/notebooks/{nb}/recordings/{doc.id}/cancel")
    assert r.status_code == 422, r.text


def test_cancel_404_when_source_in_other_notebook(client):
    nb1 = _nb(client)
    nb2 = _nb(client)
    client.app.state.ctx.recording_pipeline = _FakePipeline()
    src_id = _seed_recording(client, nb1, sources_repo.SourceStatus.EMBEDDING)
    r = client.post(f"/api/notebooks/{nb2}/recordings/{src_id}/cancel")
    assert r.status_code == 404, r.text

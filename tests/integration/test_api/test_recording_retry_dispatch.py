"""POST /recordings/{sid}/retry が圧縮音源から再STTパイプラインを再ディスパッチし、
既存チャンク(sqlite + ベクタ)をクリアすることを検証する統合テスト。

実 whisper / sherpa はロードしない。recording_pipeline を kwargs 記録 fake に差し替える。
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.storage import sources_repo
from core.storage.chunks_repo import delete_chunks_for_source  # noqa: F401  (import 健全性)


class _FakePipeline:
    def __init__(self):
        self.calls: list[dict] = []

    async def run(self, **kwargs):
        self.calls.append(kwargs)


class _FakeVectorStore:
    def __init__(self):
        self.deleted: list[str] = []

    def delete_by_source(self, source_id):
        self.deleted.append(source_id)

    def close(self):
        pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        ctx = c.app.state.ctx
        ctx.transcriber_factory = lambda: object()
        ctx.diarizer_factory = lambda: None
        yield c


def _create_nb(client) -> str:
    return client.post("/api/notebooks", json={"name": "retry"}).json()["id"]


def _seed_recording(client, nb, *, with_audio: bool, channel="mic", ext=".m4a"):
    ctx = client.app.state.ctx
    src = sources_repo.create_source(
        ctx.conn, notebook_id=nb, kind="recording", title="rec", origin="録音"
    )
    d = ctx.config.sources_dir / src.id
    d.mkdir(parents=True, exist_ok=True)
    if with_audio:
        (d / f"{channel}{ext}").write_bytes(b"\x00" * 256)
    # 0チャンク・ready のまま終わった録音を模す
    sources_repo.update_source_status(
        ctx.conn, src.id, status=sources_repo.SourceStatus.READY, chunk_count=0
    )
    return src.id


def test_retry_dispatches_pipeline_from_compressed_audio(client):
    nb = _create_nb(client)
    fake = _FakePipeline()
    fakevs = _FakeVectorStore()
    client.app.state.ctx.recording_pipeline = fake
    client.app.state.ctx.vector_store = fakevs

    src_id = _seed_recording(client, nb, with_audio=True, channel="mic", ext=".m4a")

    r = client.post(f"/api/notebooks/{nb}/recordings/{src_id}/retry")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source_id"] == src_id
    assert body["status"] == "processing"

    # ベクタ削除が呼ばれた
    assert fakevs.deleted == [src_id]

    # パイプラインが再ディスパッチされ、mic 音源が Path で渡る
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["source_id"] == src_id
    assert call["notebook_id"] == nb
    assert isinstance(call["mic_wav"], Path)
    assert call["mic_wav"].name == "mic.m4a"
    assert call["system_wav"] is None
    assert call["transcriber"] is not None
    assert "diarizer" in call

    # status が parsing 以降へ
    src = sources_repo.get_source(client.app.state.ctx.conn, src_id)
    assert src.status in (
        sources_repo.SourceStatus.PARSING,
        sources_repo.SourceStatus.READY,
    )


def test_retry_422_when_no_audio(client):
    nb = _create_nb(client)
    client.app.state.ctx.recording_pipeline = _FakePipeline()
    src_id = _seed_recording(client, nb, with_audio=False)

    r = client.post(f"/api/notebooks/{nb}/recordings/{src_id}/retry")
    assert r.status_code == 422, r.text


def test_retry_rejects_non_recording_source(client):
    nb = _create_nb(client)
    client.app.state.ctx.recording_pipeline = _FakePipeline()
    ctx = client.app.state.ctx
    doc = sources_repo.create_source(
        ctx.conn, notebook_id=nb, kind="pdf", title="doc", origin="a.pdf"
    )
    r = client.post(f"/api/notebooks/{nb}/recordings/{doc.id}/retry")
    assert r.status_code == 422, r.text


def test_retry_404_when_source_in_other_notebook(client):
    nb1 = _create_nb(client)
    nb2 = _create_nb(client)
    client.app.state.ctx.recording_pipeline = _FakePipeline()
    src_id = _seed_recording(client, nb1, with_audio=True)
    r = client.post(f"/api/notebooks/{nb2}/recordings/{src_id}/retry")
    assert r.status_code == 404, r.text


@pytest.mark.parametrize("busy", ["parsing", "chunking", "embedding"])
def test_retry_409_while_conversion_in_progress(client, busy):
    """変換の遷移中 status では retry を 409 で拒否する(二重起動ガード)。

    2026-07-04 実機で再試行の2連打により同一ソースへ2本のパイプラインが
    同時ディスパッチされていた。起動時リコンシリエーションにより、実行時に
    遷移中 status = 本当に実行中とみなせる。
    """
    nb = _create_nb(client)
    pipeline = _FakePipeline()
    client.app.state.ctx.recording_pipeline = pipeline
    src_id = _seed_recording(client, nb, with_audio=True)
    ctx = client.app.state.ctx
    sources_repo.update_source_status(
        ctx.conn, src_id, status=sources_repo.SourceStatus(busy)
    )

    r = client.post(f"/api/notebooks/{nb}/recordings/{src_id}/retry")
    assert r.status_code == 409, r.text
    assert "変換" in r.json()["detail"]
    # パイプラインはディスパッチされない
    assert pipeline.calls == []

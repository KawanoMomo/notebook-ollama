"""停止時の永続化(マーカー/リンク/タイトル) + パイプラインのページ割当(spec §4/§6)。

test_recording_markers_api.py の TestClient fake 群と、
test_recording_pipeline_fake.py の RecordingPipeline fake 群をそれぞれ踏襲する。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.recording.recording_pipeline import RecordingPipeline, RecordingPipelineDeps
from core.recording.transcriber import TranscriptSegment
from core.storage import sources_repo
from core.storage.database import migrate
from core.storage.source_links_repo import get_parent_link
from core.storage.source_markers_repo import MarkerRecord, insert_markers, list_markers
from tests.integration.test_recording_pipeline_fake import (
    FakeBroker,
    FakeDiarizer,
    FakeOllama,
    FakeTranscriber,
    FakeVectorStore,
)

# --- API 側: 停止時の永続化 (TestClient) ------------------------------------


class _FakeRecorder:
    def __init__(self, session_dir):
        self.session_dir = session_dir

    def start(self, **kwargs):
        pass

    def stop(self):
        return {"mic": None, "system": None}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        c.app.state.ctx.recorder_factory = lambda session_dir: _FakeRecorder(session_dir)
        c.app.state.ctx.transcriber_factory = lambda: None
        c.app.state.ctx.diarizer_factory = lambda: None
        yield c


def _make_notebook(client) -> str:
    r = client.post("/api/notebooks", json={"name": "nb"})
    return r.json()["id"]


def _upload_pdf(client, nb: str) -> str:
    r = client.post(
        f"/api/notebooks/{nb}/sources",
        files={"file": ("slides.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert r.status_code == 202, r.text
    return r.json()["id"]


def _start(client, nb: str, presentation_source_id: str | None = None):
    body: dict = {"live_caption": False}
    if presentation_source_id is not None:
        body["presentation_source_id"] = presentation_source_id
    return client.post(f"/api/notebooks/{nb}/recordings", json=body)


def test_stop_persists_markers_and_creates_link_and_title(client):
    nb = _make_notebook(client)
    pdf_id = _upload_pdf(client, nb)
    ctx = client.app.state.ctx
    # アップロードされた擬似PDFバイト列は実PDFではないため pymupdf 解析が失敗し
    # title は None のまま残る(ingestion は background task で握りつぶし error に
    # 落ちるだけ)。ここで検証したいのは stop 側のリンク/タイトル確定ロジックなので、
    # 親ソースのタイトルを解析成功時と同じ状態(確定済み)に直接揃えておく。
    sources_repo.update_source_title(ctx.conn, pdf_id, "slides")

    start = _start(client, nb, presentation_source_id=pdf_id).json()
    rid = start["recording_id"]
    source_id = start["source_id"]

    client.post(
        f"/api/notebooks/{nb}/recordings/{rid}/markers",
        json={"kind": "page", "value": "1"},
    )
    client.post(
        f"/api/notebooks/{nb}/recordings/{rid}/markers",
        json={"kind": "page", "value": "2"},
    )

    r = client.post(f"/api/notebooks/{nb}/recordings/{rid}/stop")
    assert r.status_code == 200, r.text

    markers = list_markers(ctx.conn, source_id, kind="page")
    assert len(markers) == 2
    assert [m.value for m in markers] == ["1", "2"]

    link = get_parent_link(ctx.conn, source_id)
    assert link is not None
    assert link.relation == "presentation"
    assert link.parent_source_id == pdf_id
    assert link.meta and "presented_at" in link.meta

    src = sources_repo.get_source(ctx.conn, source_id)
    assert src.title is not None
    assert src.title.startswith("slides 発表 "), src.title


# --- パイプライン側: ページ割当 (Fake deps 直駆動) --------------------------


class _TwoSegmentTranscriber:
    """mic に 1 セグメント(start_ms=1000)、system に 1 セグメント(start_ms=6000)を
    返す最小 fake。ページ境界 (0,"1") / (5000,"2") を跨ぐか検証するのに十分な形。"""

    def transcribe(self, wav_path, *, channel, speaker_id, language="ja", session_id=""):
        if channel == "mic":
            return [
                TranscriptSegment(
                    id=None, session_id=session_id, channel="mic",
                    start_ms=1000, end_ms=2000, speaker_id=speaker_id,
                    text="1ページ目の発言", language="ja",
                ),
            ]
        return [
            TranscriptSegment(
                id=None, session_id=session_id, channel="system",
                start_ms=6000, end_ms=7000, speaker_id=speaker_id,
                text="2ページ目の発言", language="ja",
            ),
        ]


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    migrate(c)
    c.execute("INSERT INTO notebooks(id,name,created_at,updated_at) VALUES('nb','n','t','t')")
    c.execute(
        "INSERT INTO sources(id,notebook_id,kind,status,created_at,updated_at) "
        "VALUES('src','nb','recording','pending','t','t')"
    )
    return c


async def test_pipeline_assigns_pages_from_markers(tmp_path: Path):
    conn = _conn()
    insert_markers(conn, [
        MarkerRecord(id="m1", source_id="src", kind="page", value="1", at_ms=0),
        MarkerRecord(id="m2", source_id="src", kind="page", value="2", at_ms=5_000),
    ])
    vs = FakeVectorStore()
    ollama = FakeOllama()

    pipeline = RecordingPipeline(
        deps=RecordingPipelineDeps(
            conn=conn, vector_store=vs, ollama=ollama, embedding_model="bge-m3",
        )
    )
    await pipeline.run(
        source_id="src", notebook_id="nb",
        mic_wav=tmp_path / "mic.wav", system_wav=tmp_path / "system.wav",
        transcriber=_TwoSegmentTranscriber(), diarizer=FakeDiarizer(),
        model="qwen3", diarization_enabled=False, name_inference_enabled=False,
        name_threshold=0.7, auto_title_enabled=False,
    )

    rows = conn.execute(
        "SELECT page, start_ms FROM chunks WHERE source_id='src' ORDER BY ord"
    ).fetchall()
    assert [r["page"] for r in rows] == [1, 2]

    by_start = {v.start_ms: v.page for v in vs.upserts}
    assert by_start[1000] == 1
    assert by_start[6000] == 2


async def test_pipeline_without_markers_keeps_page_none(tmp_path: Path):
    """マーカー0件の通常録音では従来どおり page は全て None(挙動不変)。"""
    conn = _conn()
    vs = FakeVectorStore()
    ollama = FakeOllama()
    broker = FakeBroker()

    pipeline = RecordingPipeline(
        deps=RecordingPipelineDeps(
            conn=conn, vector_store=vs, ollama=ollama,
            embedding_model="bge-m3", broker=broker,
        )
    )
    await pipeline.run(
        source_id="src", notebook_id="nb",
        mic_wav=tmp_path / "mic.wav", system_wav=tmp_path / "system.wav",
        transcriber=FakeTranscriber(), diarizer=FakeDiarizer(),
        model="qwen3", diarization_enabled=True, name_inference_enabled=True,
        name_threshold=0.7,
    )

    rows = conn.execute("SELECT page FROM chunks WHERE source_id='src'").fetchall()
    assert rows, "no chunks inserted"
    assert all(r["page"] is None for r in rows)
    assert vs.upserts
    assert all(v.page is None for v in vs.upserts)

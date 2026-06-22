"""stop_recording が録音オフラインパイプラインを background task として
ディスパッチすることを検証する統合テスト。

実モデル (whisper / sherpa) は一切ロードしない:
- transcriber_factory / diarizer_factory のテストフックで fake を注入し、
- recording_pipeline を、run の kwargs を記録するだけの fake に差し替える。

test_recordings_api.py の fake recorder パターンをミラーしている。
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.storage import sources_repo


class _FakeRecorder:
    """No real audio. stop() returns the on-disk wav paths we pre-seeded."""

    def __init__(self, session_dir):
        self.session_dir = Path(session_dir)
        self.started = False
        self.stopped = False

    def start(self, **k):
        self.started = True

    def stop(self):
        self.stopped = True
        # mic.wav was written into the session dir by the test (present, >64B);
        # system.wav was never created (absent).
        return {
            "mic": str(self.session_dir / "mic.wav"),
            "system": str(self.session_dir / "system.wav"),
        }


class _FakeTranscriber:
    """Sentinel; never called because the pipeline is faked."""


class _FakePipeline:
    """Records every run() invocation's kwargs without doing any real work."""

    def __init__(self):
        self.calls: list[dict] = []

    async def run(self, **kwargs):
        self.calls.append(kwargs)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        ctx = c.app.state.ctx
        # No real WASAPI / whisper / sherpa anywhere in this test.
        ctx.recorder_factory = lambda session_dir: _FakeRecorder(session_dir)
        ctx.transcriber_factory = lambda: _FakeTranscriber()
        ctx.diarizer_factory = lambda: None  # simulate models absent -> no diarization
        yield c


def _create_nb(client) -> str:
    r = client.post("/api/notebooks", json={"name": "録音ディスパッチ"})
    return r.json()["id"]


def test_stop_dispatches_offline_pipeline_as_background_task(client):
    nb = _create_nb(client)

    # Replace the real pipeline with a fake that records run() kwargs.
    fake_pipeline = _FakePipeline()
    client.app.state.ctx.recording_pipeline = fake_pipeline

    # Start a recording (no live captions -> no live transcriber needed).
    r = client.post(f"/api/notebooks/{nb}/recordings", json={"live_caption": False})
    assert r.status_code == 200, r.text
    rid = r.json()["recording_id"]
    src_id = r.json()["source_id"]

    # Seed a small (>64 byte) dummy mic.wav so it's treated as PRESENT.
    session_dir = client.app.state.ctx.config.sources_dir / src_id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "mic.wav").write_bytes(b"RIFF" + b"\x00" * 200)
    # system.wav intentionally NOT created -> absent.

    # Stop -> should dispatch the pipeline.
    r_stop = client.post(f"/api/notebooks/{nb}/recordings/{rid}/stop")
    assert r_stop.status_code == 200, r_stop.text
    body = r_stop.json()

    # 1. stop returns "processing".
    assert body["status"] == "processing"
    assert body["source_id"] == src_id
    assert body["recording_id"] == rid

    # 2. the background task ran (TestClient runs background tasks after the
    #    response is sent) and dispatched pipeline.run with the right kwargs.
    assert len(fake_pipeline.calls) == 1, "pipeline.run was not dispatched"
    call = fake_pipeline.calls[0]
    assert call["source_id"] == src_id
    assert call["notebook_id"] == nb
    assert isinstance(call["mic_wav"], Path)  # present wav -> Path
    assert call["mic_wav"].name == "mic.wav"
    assert call["system_wav"] is None  # absent wav -> None
    assert call["transcriber"] is not None  # fake transcriber injected
    # diarizer may be None (models absent / factory returns None) -- that's fine.
    assert "diarizer" in call
    assert isinstance(call["diarization_enabled"], bool)
    assert call["diarization_enabled"] is False  # diarizer is None here
    assert isinstance(call["name_inference_enabled"], bool)
    # auto_title flag is threaded from config (default True).
    assert call["auto_title_enabled"] is True

    # 3. the source moved off "pending" (status set to parsing before dispatch).
    src = sources_repo.get_source(client.app.state.ctx.conn, src_id)
    assert src.status in (
        sources_repo.SourceStatus.PARSING,
        sources_repo.SourceStatus.CHUNKING,
        sources_repo.SourceStatus.EMBEDDING,
        sources_repo.SourceStatus.READY,
    ), f"source stuck at {src.status}"


def test_stop_treats_zero_byte_wav_as_absent(client):
    """A header-only / zero-byte wav must be passed to the pipeline as None so it
    doesn't try to transcribe an empty file."""
    nb = _create_nb(client)
    fake_pipeline = _FakePipeline()
    client.app.state.ctx.recording_pipeline = fake_pipeline

    r = client.post(f"/api/notebooks/{nb}/recordings", json={"live_caption": False})
    assert r.status_code == 200, r.text
    rid = r.json()["recording_id"]
    src_id = r.json()["source_id"]

    session_dir = client.app.state.ctx.config.sources_dir / src_id
    session_dir.mkdir(parents=True, exist_ok=True)
    # mic.wav is tiny (<=64 bytes) -> treated as absent.
    (session_dir / "mic.wav").write_bytes(b"RIFF" + b"\x00" * 8)

    r_stop = client.post(f"/api/notebooks/{nb}/recordings/{rid}/stop")
    assert r_stop.status_code == 200, r_stop.text

    assert len(fake_pipeline.calls) == 1
    call = fake_pipeline.calls[0]
    assert call["mic_wav"] is None  # <=64 byte wav -> absent
    assert call["system_wav"] is None


def test_stop_persists_mute_intervals_json(client):
    """A session with accumulated mute intervals writes mute_intervals.json into
    the recording dir on stop (alongside mic.wav / system.wav)."""
    import json

    nb = _create_nb(client)
    fake_pipeline = _FakePipeline()
    client.app.state.ctx.recording_pipeline = fake_pipeline

    r = client.post(f"/api/notebooks/{nb}/recordings", json={"live_caption": False})
    assert r.status_code == 200, r.text
    rid = r.json()["recording_id"]
    src_id = r.json()["source_id"]

    # Simulate a mute toggle during recording by driving the session mute state
    # directly (no real audio device needed): mute mic, then unmute.
    sess = client.app.state.ctx.recordings.get(rid)
    ms = sess.extras["mute_state"]
    ms.set_muted("mic", True, 1000)
    ms.set_muted("mic", False, 2000)
    # leave system muted/open so close_all has to close it at stop
    ms.set_muted("system", True, 1500)

    session_dir = client.app.state.ctx.config.sources_dir / src_id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "mic.wav").write_bytes(b"RIFF" + b"\x00" * 200)

    r_stop = client.post(f"/api/notebooks/{nb}/recordings/{rid}/stop")
    assert r_stop.status_code == 200, r_stop.text

    out = session_dir / "mute_intervals.json"
    assert out.exists(), "mute_intervals.json was not written on stop"
    data = json.loads(out.read_text(encoding="utf-8"))
    # version 1: alignment メタ + t0 相対の mic/system 区間
    assert data["version"] == 1
    assert data["wav_start_offset_ms"] == 0  # fake recorder は frame を出さない
    assert data["mic"] == [{"start_ms": 1000, "end_ms": 2000}]
    # the open system interval was closed by close_all at recording end
    assert len(data["system"]) == 1
    sys_iv = data["system"][0]
    assert sys_iv["start_ms"] == 1500
    assert sys_iv["end_ms"] >= sys_iv["start_ms"]


def test_stop_writes_empty_mute_intervals_when_never_muted(client):
    """No mute toggles -> mute_intervals.json still written with empty arrays."""
    import json

    nb = _create_nb(client)
    fake_pipeline = _FakePipeline()
    client.app.state.ctx.recording_pipeline = fake_pipeline

    r = client.post(f"/api/notebooks/{nb}/recordings", json={"live_caption": False})
    rid = r.json()["recording_id"]
    src_id = r.json()["source_id"]
    session_dir = client.app.state.ctx.config.sources_dir / src_id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "mic.wav").write_bytes(b"RIFF" + b"\x00" * 200)

    r_stop = client.post(f"/api/notebooks/{nb}/recordings/{rid}/stop")
    assert r_stop.status_code == 200, r_stop.text

    out = session_dir / "mute_intervals.json"
    assert out.exists()
    # version 1 形状(version + wav_start_offset_ms + 空の mic/system 配列)。
    # 実オーディオを録っていない(fake recorder)ので wav_t0 は未取得 -> offset 0。
    assert json.loads(out.read_text(encoding="utf-8")) == {
        "version": 1,
        "wav_start_offset_ms": 0,
        "mic": [],
        "system": [],
    }


def test_retry_threads_auto_title_flag(client):
    nb = _create_nb(client)
    fake_pipeline = _FakePipeline()
    client.app.state.ctx.recording_pipeline = fake_pipeline
    # auto_title を OFF にしておく(in-memory config を直接いじる)。
    client.app.state.ctx.config.audio.auto_title = False

    # 録音ソースを直接作成(start/stop は経由しない)+ 再処理用の圧縮音源を置く。
    from core.storage import sources_repo

    src = sources_repo.create_source(
        client.app.state.ctx.conn,
        notebook_id=nb,
        kind="recording",
        title=None,
        origin="録音",
    )
    session_dir = client.app.state.ctx.config.sources_dir / src.id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "mic.m4a").write_bytes(b"\x00" * 256)

    r_retry = client.post(f"/api/notebooks/{nb}/recordings/{src.id}/retry")
    assert r_retry.status_code == 200, r_retry.text
    assert len(fake_pipeline.calls) == 1
    assert fake_pipeline.calls[0]["auto_title_enabled"] is False

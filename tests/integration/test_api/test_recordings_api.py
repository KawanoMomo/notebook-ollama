import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


class _FakeRecorder:
    """No real audio: records that start/stop were called and returns empty paths."""

    def __init__(self, session_dir):
        self.session_dir = session_dir
        self.started = False
        self.stopped = False

    def start(self, **k):
        self.started = True

    def stop(self):
        self.stopped = True
        return {"mic": None, "system": None}


class _FailingRecorder(_FakeRecorder):
    """Simulates a real WASAPI device-open failure on start()."""

    def start(self, **k):
        raise RuntimeError("device open failed")


class _FakeTranscriber:
    """Sentinel transcriber so stop() never loads a real whisper model."""


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        # Inject the fake recorder AFTER build_context has run (lifespan triggered
        # by entering the TestClient context manager). The router reads this via
        # getattr, so no real Recorder / WASAPI is ever touched.
        c.app.state.ctx.recorder_factory = lambda session_dir: _FakeRecorder(session_dir)
        # stop() now lazily builds a transcriber for the offline pipeline; inject a
        # fake so no real whisper model is downloaded/loaded in these tests.
        c.app.state.ctx.transcriber_factory = lambda: _FakeTranscriber()
        c.app.state.ctx.diarizer_factory = lambda: None
        yield c


def _create_nb(client) -> str:
    r = client.post("/api/notebooks", json={"name": "録音テスト"})
    return r.json()["id"]


def test_start_recording_creates_source_and_returns_recording(client):
    nb = _create_nb(client)
    r = client.post(f"/api/notebooks/{nb}/recordings", json={"live_caption": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source_id"]
    assert body["recording_id"]
    assert body["status"] == "recording"
    assert body["live_caption"] is False

    # a recording-kind source row now exists for the notebook
    r2 = client.get(f"/api/notebooks/{nb}/sources")
    assert r2.status_code == 200
    sources = r2.json()
    assert any(
        s["id"] == body["source_id"] and s["kind"] == "recording" for s in sources
    )


def test_second_start_while_active_returns_409(client):
    nb = _create_nb(client)
    r1 = client.post(f"/api/notebooks/{nb}/recordings", json={"live_caption": False})
    assert r1.status_code == 200, r1.text

    r2 = client.post(f"/api/notebooks/{nb}/recordings", json={"live_caption": False})
    assert r2.status_code == 409


def test_stop_recording_returns_pending_with_paths(client):
    nb = _create_nb(client)
    r = client.post(f"/api/notebooks/{nb}/recordings", json={"live_caption": False})
    assert r.status_code == 200, r.text
    rid = r.json()["recording_id"]

    r_stop = client.post(f"/api/notebooks/{nb}/recordings/{rid}/stop")
    assert r_stop.status_code == 200, r_stop.text
    body = r_stop.json()
    # stop now dispatches the offline ingestion pipeline -> "processing".
    assert body["status"] == "processing"
    assert body["recording_id"] == rid
    assert "paths" in body
    assert set(body["paths"].keys()) == {"mic", "system"}


def test_stop_unknown_recording_returns_400(client):
    nb = _create_nb(client)
    r = client.post(f"/api/notebooks/{nb}/recordings/does-not-exist/stop")
    assert r.status_code == 400


def test_recorder_start_failure_frees_registry_and_marks_source_error(client):
    nb = _create_nb(client)

    # First attempt uses a recorder whose start() raises -> must NOT brick recording.
    client.app.state.ctx.recorder_factory = lambda session_dir: _FailingRecorder(session_dir)
    r = client.post(f"/api/notebooks/{nb}/recordings", json={"live_caption": False})
    assert r.status_code == 500, r.text
    # capture the failed source id before listing
    sources = client.get(f"/api/notebooks/{nb}/sources").json()
    failed = [s for s in sources if s["kind"] == "recording"]
    assert len(failed) == 1
    assert failed[0]["status"] == "error"

    # Registry must be freed: a subsequent start with a WORKING recorder succeeds
    # (no permanent 409).
    client.app.state.ctx.recorder_factory = lambda session_dir: _FakeRecorder(session_dir)
    r2 = client.post(f"/api/notebooks/{nb}/recordings", json={"live_caption": False})
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "recording"


def test_stop_recording_wrong_notebook_returns_404(client):
    nb = _create_nb(client)
    other = _create_nb(client)
    r = client.post(f"/api/notebooks/{nb}/recordings", json={"live_caption": False})
    rid = r.json()["recording_id"]
    # stop via a different notebook id -> 404, and the session stays active
    r404 = client.post(f"/api/notebooks/{other}/recordings/{rid}/stop")
    assert r404.status_code == 404
    # original notebook can still stop it
    r_ok = client.post(f"/api/notebooks/{nb}/recordings/{rid}/stop")
    assert r_ok.status_code == 200

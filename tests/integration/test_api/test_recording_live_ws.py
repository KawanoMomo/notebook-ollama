import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


class _FakeRecorder:
    """No real audio: records that start/stop were called and returns empty paths.

    Accepts (and ignores) the mic/system chunk callbacks the start path now passes.
    """

    def __init__(self, session_dir):
        self.session_dir = session_dir
        self.started = False
        self.stopped = False

    def start(self, **k):
        self.started = True

    def stop(self):
        self.stopped = True
        return {"mic": None, "system": None}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        # Inject the fake recorder so no real Recorder / WASAPI is ever touched.
        c.app.state.ctx.recorder_factory = lambda session_dir: _FakeRecorder(session_dir)
        yield c


def _create_nb(client) -> str:
    r = client.post("/api/notebooks", json={"name": "録音WSテスト"})
    return r.json()["id"]


def _start_recording(client, nb) -> str:
    # live_caption=False so NO real transcriber/model is created. The start path
    # still creates sess.extras["queue"], which the WS drains.
    r = client.post(f"/api/notebooks/{nb}/recordings", json={"live_caption": False})
    assert r.status_code == 200, r.text
    assert r.json()["live_caption"] is False
    return r.json()["recording_id"]


def test_live_ws_streams_queued_caption(client):
    nb = _create_nb(client)
    rid = _start_recording(client, nb)

    caption = {
        "type": "caption", "id": "mic-1", "label": "あなた",
        "text": "テスト", "start_ms": 0, "end_ms": 500,
    }
    sess = client.app.state.ctx.recordings.get(rid)
    assert sess is not None
    sess.extras["queue"].put_nowait(caption)

    with client.websocket_connect(f"/ws/recordings/{rid}/live") as ws:
        data = ws.receive_json()
    assert data == caption


def test_live_ws_unknown_recording_sends_error(client):
    with client.websocket_connect("/ws/recordings/does-not-exist/live") as ws:
        data = ws.receive_json()
    assert "error" in data


def test_live_gain_unknown_recording_returns_404(client):
    nb = _create_nb(client)
    r = client.put(
        f"/api/notebooks/{nb}/recordings/does-not-exist/live-gain",
        json={"mic_db": 5.0, "sys_db": 3.0},
    )
    assert r.status_code == 404


def test_live_gain_without_workers_returns_ok_clamped(client):
    nb = _create_nb(client)
    rid = _start_recording(client, nb)

    # No live-caption workers exist (live_caption=False), but the endpoint still
    # clamps and echoes the requested values. manual_boost_max_db default = 18.0.
    r = client.put(
        f"/api/notebooks/{nb}/recordings/{rid}/live-gain",
        json={"mic_db": 100.0, "sys_db": -5.0},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["mic_db"] == 18.0
    assert body["sys_db"] == 0.0

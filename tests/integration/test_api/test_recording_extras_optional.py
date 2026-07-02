"""Regression: app must boot when the `recording` extra is not installed.

`apps/api/dependencies.py` catches a `ModuleNotFoundError` from
`core.recording.recording_pipeline` and degrades by setting
`ctx.recording_pipeline = None`. The recording endpoints then surface this
as HTTP 503 instead of crashing the worker at import time.

These tests simulate the missing-extra condition by:
  1. Building a real `AppContext` with a temp data dir.
  2. Setting `ctx.recording_pipeline = None` AFTER build_context returns
     (matches the runtime state when soundfile / faster-whisper are absent).
  3. Driving the FastAPI app through the public REST endpoints and asserting
     the 503 contract (start / stop / retry) and that unrelated endpoints
     (notebooks / sources list) keep working.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.dependencies import build_context
from apps.api.main import create_app
from core.config import AppConfig


def test_build_context_succeeds_when_recording_pipeline_init_fails(tmp_path, monkeypatch):
    """If core.recording.recording_pipeline raises ModuleNotFoundError at
    import time, build_context must log a warning and set recording_pipeline
    to None — NOT propagate the exception."""

    # Make the `from core.recording.recording_pipeline import ...` inside
    # build_context fail as if the `recording` extra were uninstalled.
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "core.recording.recording_pipeline":
            raise ModuleNotFoundError("No module named 'soundfile'", name="soundfile")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    cfg = AppConfig(data_dir=tmp_path)
    ctx = build_context(cfg)

    assert ctx.recording_pipeline is None
    # The rest of the wiring must still be intact.
    assert ctx.conn is not None
    assert ctx.vector_store is not None
    assert ctx.pipeline is not None
    assert ctx.generation is not None


@pytest.fixture
def client_without_recording(tmp_path, monkeypatch):
    """TestClient whose ctx has recording_pipeline=None (extras missing case)."""
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        c.app.state.ctx.recording_pipeline = None
        yield c


def _create_nb(client) -> str:
    r = client.post("/api/notebooks", json={"name": "録音 extra なし"})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_start_recording_returns_503_when_extras_missing(client_without_recording):
    nb = _create_nb(client_without_recording)
    r = client_without_recording.post(
        f"/api/notebooks/{nb}/recordings", json={"live_caption": False}
    )
    assert r.status_code == 503, r.text
    assert "recording extras not installed" in r.json()["detail"]
    assert "uv sync --extra recording" in r.json()["detail"]


def test_stop_recording_returns_503_when_extras_missing(client_without_recording):
    nb = _create_nb(client_without_recording)
    r = client_without_recording.post(
        f"/api/notebooks/{nb}/recordings/anything/stop"
    )
    assert r.status_code == 503, r.text
    assert "recording extras not installed" in r.json()["detail"]


def test_retry_recording_returns_503_when_extras_missing(client_without_recording):
    nb = _create_nb(client_without_recording)
    r = client_without_recording.post(
        f"/api/notebooks/{nb}/recordings/anything/retry"
    )
    assert r.status_code == 503, r.text
    assert "recording extras not installed" in r.json()["detail"]


def test_notebooks_list_still_works_when_extras_missing(client_without_recording):
    """Unrelated endpoints must keep working — the degrade is scoped to
    recording endpoints only."""
    r = client_without_recording.get("/api/notebooks")
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)

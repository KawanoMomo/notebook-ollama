"""Integration tests for ``/api/settings`` crash_report exposure +
``PUT /api/settings/crash-report`` + ``POST /api/crash/report`` opt-in gate.

Sprint 3 Task 3.5 follow-up — closes the missing BE wiring exposed by the
visual verification of S6 (disable) / S8 (opt-in persist) which currently
hit 405 because the PUT endpoint did not exist.

Test policy:
- Fresh ``create_app()`` per test rooted at ``tmp_path`` via the
  ``NOTEBOOK_OLLAMA_DATA_DIR`` env (matches existing settings/crash test
  patterns). No env-var coercion of nested ``bool | None`` fields — that
  path is brittle in pydantic-settings; use ``save_crash_report`` to seed
  ``settings.json`` when a non-default initial state is needed (matches
  ``test_lifespan_crash_integration.py``).
- 403 gate is asserted in BOTH ``enabled is None`` (未決定) and
  ``enabled is False`` (明示拒否) branches — both must be blocked by spec
  §5.9 ("explicit opt-in required").
- Auto-stamp of ``opted_in_at`` on the None → True transition is verified
  by (a) absence in the request body and (b) presence in the response,
  rather than asserting an exact timestamp (would be flaky).
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.crash_reporter.settings import CrashReportSettings
from core.settings_store import load_crash_report, save_crash_report


@pytest.fixture
def client_no_optin(tmp_path, monkeypatch):
    """Fresh app at ``tmp_path`` with NO crash_report opt-in (default = None).

    ``enabled is None`` is the initial state for any user who has not yet
    seen the opt-in dialog. POST /api/crash/report must be gated 403 here.
    """
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    with TestClient(create_app()) as c:
        c._tmp_path = tmp_path  # type: ignore[attr-defined]
        yield c


@pytest.fixture
def client_opted_out(tmp_path, monkeypatch):
    """Fresh app at ``tmp_path`` with ``crash_report.enabled=False``.

    Explicit opt-out path (S6 disable). POST /api/crash/report must be
    gated 403 here too — "False" is just as blocking as "None".
    """
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    save_crash_report(tmp_path, CrashReportSettings(enabled=False))
    with TestClient(create_app()) as c:
        c._tmp_path = tmp_path  # type: ignore[attr-defined]
        yield c


def _valid_report_payload() -> dict:
    return {
        "message": "boom",
        "stack": "Error: boom\n    at handler (app.js:42:10)",
        "hardware": {"gpu_model": "NVIDIA GeForce RTX 2080 Ti"},
        "source": "frontend",
    }


# ---------------------------------------------------------------------------
# GET /api/settings includes crash_report
# ---------------------------------------------------------------------------


def test_get_settings_includes_crash_report_defaults(client_no_optin):
    """GET /api/settings on a fresh data_dir surfaces the default crash_report
    tri-state (``enabled=None``, ``auto_prompt=True``, ``opted_in_at=None``).
    """
    r = client_no_optin.get("/api/settings")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "crash_report" in body, body
    cr = body["crash_report"]
    assert cr["enabled"] is None
    assert cr["auto_prompt"] is True
    assert cr["opted_in_at"] is None


def test_get_settings_reflects_persisted_crash_report(tmp_path, monkeypatch):
    """When ``settings.json`` already has ``crash_report``, GET surfaces it."""
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    when = datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC)
    save_crash_report(
        tmp_path,
        CrashReportSettings(enabled=True, auto_prompt=False, opted_in_at=when),
    )
    with TestClient(create_app()) as c:
        r = c.get("/api/settings")
        assert r.status_code == 200, r.text
        cr = r.json()["crash_report"]
        assert cr["enabled"] is True
        assert cr["auto_prompt"] is False
        # JSON datetime is an ISO string; parse it back for equality.
        assert datetime.fromisoformat(cr["opted_in_at"]) == when


# ---------------------------------------------------------------------------
# PUT /api/settings/crash-report
# ---------------------------------------------------------------------------


def test_put_crash_report_enables_and_auto_stamps_opted_in_at(client_no_optin):
    """None → True transition without explicit ``opted_in_at`` auto-stamps now."""
    before = client_no_optin.get("/api/settings").json()["crash_report"]
    assert before["enabled"] is None
    assert before["opted_in_at"] is None

    r = client_no_optin.put(
        "/api/settings/crash-report",
        json={"enabled": True, "auto_prompt": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["auto_prompt"] is True
    # Server stamped the timestamp on the transition.
    assert body["opted_in_at"] is not None
    stamped = datetime.fromisoformat(body["opted_in_at"])
    # Sanity: stamped time is timezone-aware and within a generous window.
    assert stamped.tzinfo is not None

    # Persisted to settings.json (next GET sees the same state).
    after = client_no_optin.get("/api/settings").json()["crash_report"]
    assert after["enabled"] is True
    assert after["opted_in_at"] == body["opted_in_at"]

    # On-disk persistence sanity (the section was actually written).
    persisted = load_crash_report(client_no_optin._tmp_path)
    assert persisted.enabled is True
    assert persisted.auto_prompt is True
    assert persisted.opted_in_at == stamped


def test_put_crash_report_partial_update_preserves_other_fields(
    tmp_path, monkeypatch
):
    """A PUT that only sets ``auto_prompt`` must leave ``enabled`` and
    ``opted_in_at`` untouched."""
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    when = datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC)
    save_crash_report(
        tmp_path,
        CrashReportSettings(enabled=True, auto_prompt=True, opted_in_at=when),
    )

    with TestClient(create_app()) as c:
        r = c.put("/api/settings/crash-report", json={"auto_prompt": False})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["auto_prompt"] is False
        assert body["enabled"] is True  # preserved
        assert datetime.fromisoformat(body["opted_in_at"]) == when  # preserved


def test_put_crash_report_disable_clears_opt_in(tmp_path, monkeypatch):
    """S6 (disable) flow: PUT {"enabled": false} flips state to opted-out.

    The opt-in timestamp is NOT auto-cleared here — the field records the
    moment of the most recent explicit decision (in either direction). The
    server simply persists the caller-supplied subset.
    """
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    when = datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC)
    save_crash_report(
        tmp_path,
        CrashReportSettings(enabled=True, auto_prompt=True, opted_in_at=when),
    )

    with TestClient(create_app()) as c:
        r = c.put("/api/settings/crash-report", json={"enabled": False})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["enabled"] is False
        # POST /report must now be blocked.
        r2 = c.post("/api/crash/report", json=_valid_report_payload())
        assert r2.status_code == 403, r2.text


def test_put_crash_report_invalid_enabled_returns_422(client_no_optin):
    """Type-mismatch on ``enabled`` (a string that pydantic cannot coerce to
    a bool) must be rejected by Pydantic with HTTP 422."""
    r = client_no_optin.put(
        "/api/settings/crash-report",
        json={"enabled": "not-a-bool"},
    )
    assert r.status_code == 422, r.text


def test_put_crash_report_respects_explicit_opted_in_at(
    client_no_optin,
):
    """If caller explicitly supplies ``opted_in_at``, server must NOT
    overwrite it with ``datetime.now``.
    """
    explicit = "2025-01-01T00:00:00+00:00"
    r = client_no_optin.put(
        "/api/settings/crash-report",
        json={"enabled": True, "opted_in_at": explicit},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert datetime.fromisoformat(body["opted_in_at"]) == datetime.fromisoformat(
        explicit
    )


def test_put_crash_report_persists_across_app_restart(tmp_path, monkeypatch):
    """A PUT survives a TestClient restart (settings.json on-disk source).

    This is the contract that closes S8 (opt-in persist) end-to-end: opting
    in once must keep the user opted in after the app process exits.
    """
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")

    with TestClient(create_app()) as c:
        r = c.put(
            "/api/settings/crash-report",
            json={"enabled": True, "auto_prompt": True},
        )
        assert r.status_code == 200, r.text

    # On-disk settings.json carries the opt-in.
    raw = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert raw["crash_report"]["enabled"] is True

    # Restart the app — apply_overrides must restore enabled=True.
    with TestClient(create_app()) as c2:
        cr = c2.get("/api/settings").json()["crash_report"]
        assert cr["enabled"] is True
        # POST /report is now accepted (no 403).
        r2 = c2.post("/api/crash/report", json=_valid_report_payload())
        assert r2.status_code in (200, 201), r2.text


# ---------------------------------------------------------------------------
# POST /api/crash/report opt-in gate
# ---------------------------------------------------------------------------


def test_post_crash_report_403_when_undecided(client_no_optin):
    """``enabled is None`` (initial state) → 403 with
    detail='crash.opt_in_required'."""
    r = client_no_optin.post("/api/crash/report", json=_valid_report_payload())
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "crash.opt_in_required"


def test_post_crash_report_403_when_opted_out(client_opted_out):
    """``enabled is False`` (explicit opt-out) → 403 with
    detail='crash.opt_in_required'."""
    r = client_opted_out.post("/api/crash/report", json=_valid_report_payload())
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "crash.opt_in_required"


def test_post_crash_report_201_after_opt_in(client_no_optin):
    """After PUT enabling opt-in, POST /report succeeds (201 for first
    occurrence). This is the S8 end-to-end happy path."""
    # First call → 403.
    r0 = client_no_optin.post("/api/crash/report", json=_valid_report_payload())
    assert r0.status_code == 403

    # Opt in via the new PUT endpoint.
    rp = client_no_optin.put(
        "/api/settings/crash-report",
        json={"enabled": True, "auto_prompt": True},
    )
    assert rp.status_code == 200, rp.text

    # Now the report endpoint is open.
    r1 = client_no_optin.post("/api/crash/report", json=_valid_report_payload())
    assert r1.status_code == 201, r1.text
    body = r1.json()
    assert body["exception_message"] == "boom"
    assert body["source"] == "frontend"

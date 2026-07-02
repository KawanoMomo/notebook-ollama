"""Integration tests for the lifespan crash-report wiring.

Sprint 4 Task 4.3 — verifies that ``apps/api/main.py::lifespan``
correctly orchestrates the crash auto-detection pipeline:

- ``crash_report.enabled is True`` → rotate prev log + install JSON-lines
  file sink + acquire ``running.lock`` + register crash traps. On
  shutdown the lock disappears and traps are unregistered.
- ``crash_report.enabled is False`` (or ``None``) → **all** of the above
  is skipped. The Feedback Hub still works through the existing routers
  (manual-only mode), but no background auto-collection runs.
- Pre-seed an unclean prior session (dead PID in ``running.lock`` +
  ``last-session.log.prev`` carrying an ERROR event) → on startup the
  ``crash-pending/`` dir gains exactly one ``.json`` file with
  ``source="unclean_shutdown"``.
- Pre-mark the would-be fingerprint as reported → the lifespan must NOT
  re-save it (spec §9 — no re-prompting the user for a known bug).
- Two consecutive ``TestClient`` runs (an app restart simulated within a
  single live test process) must not fabricate a false unclean-shutdown
  report. ``acquire`` treats a live prior PID as a ``uvicorn --reload``
  race, not a crash.

Test policy:
- Fresh ``create_app()`` per test, ``NOTEBOOK_OLLAMA_DATA_DIR`` pointed
  at ``tmp_path`` to fully isolate pending / reported stores and the
  rotated log layout from any other test's data dir.
- Crash-report opt-in is set by writing the ``settings.json`` directly
  (via :func:`core.settings_store.save_crash_report`) rather than by
  environment variables — pydantic-settings env coercion for nested
  ``bool | None`` fields is brittle, and the on-disk path is the one
  actually exercised by ``apply_overrides`` in production.
- Autouse fixture clears the in-process ``reported_store`` cache **and**
  ``crash_collector`` traps between tests so process-global state never
  leaks between cases.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.crash_reporter import collector as crash_collector
from core.crash_reporter import (
    lifecycle,
    pending_store,
    reported_store,
)
from core.crash_reporter.settings import CrashReportSettings
from core.logging import get_logger
from core.settings_store import save_crash_report

# A PID well above any sane host's PID space.
# Linux ``kernel.pid_max`` defaults to 4_194_304; Windows hands out
# 32-bit PIDs but never values this large in practice. ``psutil.pid_exists``
# returns False for unused PIDs without raising.
_GHOST_PID = 2_147_000_000


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _cleanup_global_state():
    """Tear down process-global crash-handler state and caches.

    ``crash_collector`` mutates ``sys.excepthook``, signal handlers, and
    ``atexit``; ``reported_store`` holds an in-process dedup cache keyed
    by absolute ``data_dir``. Without this fixture, a leaked handler
    from one test would fire during another test and corrupt results.
    """
    reported_store._CACHE.clear()
    crash_collector.unregister()  # idempotent on a clean state
    yield
    crash_collector.unregister()
    reported_store._CACHE.clear()


def _common_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point AppConfig at the isolated ``tmp_path`` data dir."""
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    # Avoid attempting real Ollama calls during build_context.
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")


def _opt_in(tmp_path: Path) -> None:
    """Persist ``crash_report.enabled=True`` to the tmp data_dir's
    ``settings.json`` so ``apply_overrides`` picks it up.
    """
    save_crash_report(tmp_path, CrashReportSettings(enabled=True))


def _opt_out(tmp_path: Path) -> None:
    """Persist explicit ``enabled=False`` (the "no thanks" branch)."""
    save_crash_report(tmp_path, CrashReportSettings(enabled=False))


def _seed_prev_log(tmp_path: Path, events: list[dict]) -> Path:
    """Write a fake rotated ``last-session.log.prev`` (one JSON per line).

    Note: we intentionally write only ``.prev`` and NOT ``last-session.log``.
    ``rotate_last_session`` (called inside ``configure_logging``) is a no-op
    when ``last-session.log`` does not exist, so this seeded ``.prev`` is
    not clobbered by the rotation step at startup.
    """
    prev = tmp_path / "logs" / "last-session.log.prev"
    prev.parent.mkdir(parents=True, exist_ok=True)
    with prev.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False))
            f.write("\n")
    return prev


def _seed_dead_lock(tmp_path: Path) -> Path:
    """Pre-seed ``running.lock`` with a PID that cannot exist on this host."""
    lock = tmp_path / "running.lock"
    lock.write_text(str(_GHOST_PID), encoding="utf-8")
    return lock


# ---------------------------------------------------------------------------
# happy-path: enabled=True
# ---------------------------------------------------------------------------


def test_lifespan_with_crash_enabled_writes_log_and_acquires_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``enabled=True``: ``last-session.log`` is written, ``running.lock``
    exists during the lifespan with the test process's PID, and the lock
    is removed cleanly on shutdown.

    We trigger an explicit log emission via ``get_logger`` to force the
    file sink processor to actually open + append to ``last-session.log``
    (configure_logging only opens the file lazily, on the first write).
    """
    _common_env(monkeypatch, tmp_path)
    _opt_in(tmp_path)

    lock_path = tmp_path / "running.lock"
    log_path = tmp_path / "logs" / "last-session.log"

    with TestClient(create_app()) as client:
        # Force at least one structured log event so the file sink opens.
        get_logger("lifespan_test").info("lifespan_sanity_check")
        # App is up and serving.
        assert client.get("/api/health").status_code == 200
        # Lock has been stamped with this process's PID.
        assert lock_path.is_file()
        assert lock_path.read_text(encoding="utf-8").strip() == str(os.getpid())
        # last-session.log was opened and written to by the file sink.
        assert log_path.is_file()
        assert log_path.stat().st_size > 0

    # After shutdown the lock is released.
    assert not lock_path.exists()


# ---------------------------------------------------------------------------
# opt-out: enabled=False
# ---------------------------------------------------------------------------


def test_lifespan_with_crash_disabled_skips_lock_and_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``enabled=False``: no ``last-session.log`` is created, no
    ``running.lock`` is acquired (auto-detection pipeline is dormant).

    The manual routers (``/api/crash/report``, ``/api/feedback-hub/*``)
    still work — only the background auto-collection is suspended.
    """
    _common_env(monkeypatch, tmp_path)
    _opt_out(tmp_path)

    lock_path = tmp_path / "running.lock"
    log_path = tmp_path / "logs" / "last-session.log"

    with TestClient(create_app()) as client:
        # Even with explicit logging the file sink should NOT exist
        # because ``configure_logging`` was called without ``logs_dir``.
        get_logger("lifespan_test").info("dormant_mode_sanity_check")
        assert client.get("/api/health").status_code == 200
        assert not lock_path.exists()
        assert not log_path.exists()

    assert not lock_path.exists()
    assert not log_path.exists()


def test_lifespan_with_crash_undecided_skips_lock_and_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``enabled=None`` (initial state, user not yet prompted) behaves
    identically to opt-out: the auto-detection pipeline stays dormant.

    Per spec §5.9, we must NOT collect crashes until the user has
    explicitly opted in.
    """
    _common_env(monkeypatch, tmp_path)
    # No save_crash_report call → settings.json has no crash_report
    # section → apply_overrides leaves the default (``enabled=None``).

    lock_path = tmp_path / "running.lock"
    log_path = tmp_path / "logs" / "last-session.log"

    with TestClient(create_app()) as client:
        assert client.get("/api/health").status_code == 200
        assert not lock_path.exists()
        assert not log_path.exists()


# ---------------------------------------------------------------------------
# unclean shutdown recovery
# ---------------------------------------------------------------------------


def test_lifespan_ingests_unclean_prior_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Pre-seed a dead PID in ``running.lock`` + an ERROR-level event in
    ``last-session.log.prev`` → on startup the lifespan must produce
    exactly one ``.json`` file under ``crash-pending/`` with
    ``source="unclean_shutdown"``.
    """
    _common_env(monkeypatch, tmp_path)
    _opt_in(tmp_path)

    _seed_dead_lock(tmp_path)
    _seed_prev_log(
        tmp_path,
        [
            {"level": "INFO", "event_name": "startup"},
            {
                "level": "ERROR",
                "event_name": "rag.search",
                "exception_type": "RuntimeError",
                "exception_module": "core.retrieval",
            },
        ],
    )

    with TestClient(create_app()):
        # The unclean-shutdown ingestion happens during lifespan startup,
        # so by the time we enter this block the pending file already
        # exists. We don't need to make any requests.
        pass

    pending = pending_store.load_all(tmp_path)
    assert len(pending) == 1
    crash = pending[0]
    assert crash.source == "unclean_shutdown"
    assert crash.exception_type == "RuntimeError"
    assert crash.fingerprint  # non-empty SHA1 hex


def test_lifespan_does_not_resave_reported_unclean_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Spec §9: if the would-be fingerprint is already in
    ``reported.txt``, the lifespan must NOT write a new pending file.

    Strategy: compute the fingerprint that
    ``collect_pending_from_log_tail`` would produce for the seeded ERROR
    event, pre-mark it as reported, then start the app. The lifespan
    must short-circuit and leave ``crash-pending/`` empty.
    """
    _common_env(monkeypatch, tmp_path)
    _opt_in(tmp_path)

    _seed_dead_lock(tmp_path)
    error_event = {
        "level": "ERROR",
        "event_name": "rag.search",
        "exception_type": "RuntimeError",
        "exception_module": "core.retrieval",
    }
    _seed_prev_log(tmp_path, [error_event])

    # Pre-register the fingerprint that the recovery path would compute.
    # Using the public ``mark_reported`` ensures both disk + cache reflect it.
    fingerprint = lifecycle._fingerprint_from_event(error_event)
    reported_store.mark_reported(tmp_path, fingerprint)

    with TestClient(create_app()):
        pass

    # No new pending file: dedup hit on the in-process cache.
    assert pending_store.load_all(tmp_path) == []


# ---------------------------------------------------------------------------
# restart safety: live PID must not be treated as unclean
# ---------------------------------------------------------------------------


def test_lifespan_two_consecutive_runs_does_not_fabricate_unclean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Two consecutive ``TestClient`` runs in the same process (simulating
    a restart of the FastAPI app while the host process stays alive)
    must NOT fabricate an unclean-shutdown report.

    Two complementary scenarios are exercised:

    1. Clean handoff — run 1 releases the lock on shutdown, so run 2
       sees no lock at all and produces no recovery.
    2. Lock survives with a live PID — even if release somehow did not
       fire (e.g. SIGKILL of the previous process by an external agent
       leaving the lock behind, but our PID happens to be reused), the
       prior PID is still alive in the current process, so ``acquire``
       must treat it as a ``uvicorn --reload`` race rather than a crash.
    """
    _common_env(monkeypatch, tmp_path)
    _opt_in(tmp_path)

    # Run 1: clean acquire + release lifecycle.
    with TestClient(create_app()):
        pass
    assert not (tmp_path / "running.lock").exists()
    assert pending_store.load_all(tmp_path) == []

    # Simulate "lock still present with the current alive PID" — even
    # under that pathological state, run 2 must NOT fabricate a crash.
    (tmp_path / "running.lock").write_text(str(os.getpid()), encoding="utf-8")

    with TestClient(create_app()):
        pass

    assert pending_store.load_all(tmp_path) == []
    # After shutdown the lock has been released by the second lifespan.
    assert not (tmp_path / "running.lock").exists()


# ---------------------------------------------------------------------------
# regression: existing API health must still work in both modes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("enabled", [True, False, None])
def test_lifespan_health_endpoint_works_in_every_opt_in_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool | None
):
    """The opt-in tri-state must not regress any existing route.

    Parametrise over the FULL set ``{True, False, None}`` (no hand-rolled
    subsets) so a future addition to ``CrashReportSettings.enabled``'s
    domain forces this test to cover it.
    """
    _common_env(monkeypatch, tmp_path)
    if enabled is True:
        _opt_in(tmp_path)
    elif enabled is False:
        _opt_out(tmp_path)
    # enabled is None → leave settings.json absent / unchanged.

    with TestClient(create_app()) as client:
        r = client.get("/api/health")
        assert r.status_code == 200, r.text
        assert r.json()["status"] in {"ok", "degraded"}

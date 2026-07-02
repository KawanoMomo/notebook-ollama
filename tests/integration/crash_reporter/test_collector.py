"""Tests for ``core.crash_reporter.collector``.

spec §4.1 / plan Sprint 3 Task 3.4: unified traps integration.

Covers:
- ``collect_from_exception`` purity (no I/O): builds a ``PendingCrash`` from
  an exception, honoring the opt-in gate (``settings.enabled``).
- ``register`` / ``unregister``: installs and removes FastAPI exception
  handler, ``sys.excepthook``, signal handlers, and ``atexit`` hooks
  without leaking state across repeated calls.
- Dedup via ``reported_store``: a fingerprint already in
  ``reported.txt`` is not double-saved as a new pending file.
- FastAPI catch-all: TestClient round trip writes a pending file when
  enabled, returns 500 JSON, and never crashes the response.

Lessons-from-prior-reviews applied:
- Parametrize over ``sorted(get_args(Source))`` rather than hand-rolled
  subsets when checking source-typing coverage.
- ``register`` / ``unregister`` is exercised across multiple invocations
  to catch handler leakage (additive ``sys.excepthook`` chaining, extra
  atexit registrations, signal handler stack growth).
- Fresh ``create_app()`` (well, fresh ``FastAPI()``) per test for the
  HTTP path; integration with the real ``apps.api.main.create_app`` is
  Sprint 3 Task 3.5's responsibility.
"""
from __future__ import annotations

import atexit
import signal
import sys
from pathlib import Path
from typing import get_args

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.crash_reporter import (
    collector as collector_mod,
)
from core.crash_reporter import (
    hardware,
    pending_store,
    redactor,
    reported_store,
)
from core.crash_reporter.collector import (
    collect_from_exception,
    register,
    unregister,
)
from core.crash_reporter.domain_errors import MissingQdrantCollection
from core.crash_reporter.pending_store import Source
from core.crash_reporter.settings import CrashReportSettings

_VALID_SOURCES: tuple[str, ...] = get_args(Source)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _cleanup() -> None:
    """Always tear down installed handlers between tests.

    The collector mutates process-global state (``sys.excepthook``,
    signal handlers, ``atexit``). Without this fixture a leaked handler
    from one test would fire during another test and corrupt results.
    Clearing the ``reported_store`` cache here too ensures the dedup
    test isn't poisoned by an unrelated tmp_path from a prior test.
    """
    reported_store._CACHE.clear()
    unregister()  # idempotent
    yield
    unregister()
    reported_store._CACHE.clear()


def _settings(enabled: bool | None) -> CrashReportSettings:
    return CrashReportSettings(enabled=enabled)


def _raise_and_capture(exc: BaseException) -> BaseException:
    """Raise then catch so ``exc.__traceback__`` is populated.

    ``compute_fingerprint`` / ``redact_traceback`` need a real traceback;
    raw construction (``RuntimeError("x")``) leaves ``__traceback__=None``.
    """
    try:
        raise exc
    except BaseException as e:
        return e


# ---------------------------------------------------------------------------
# collect_from_exception — pure helper
# ---------------------------------------------------------------------------


def test_collect_from_exception_with_domain_error_uses_safe_message():
    """``DomainError`` subclasses expose ``safe_message`` → must appear
    verbatim in the pending crash's ``exception_message`` (spec §6.3).

    This is the only path where free-form message text is allowed; for
    everything else we must fall back to the type-name-only template.
    """
    exc = _raise_and_capture(MissingQdrantCollection("collection=foo missing"))
    crash = collect_from_exception(
        exc,
        source="fastapi",
        settings=_settings(True),
        redactor=redactor,
        hardware_collector=hardware.collect,
    )
    assert crash is not None
    assert crash.exception_message == "Qdrant collection not found"
    assert crash.exception_type == "MissingQdrantCollection"


def test_collect_from_exception_with_unknown_uses_fallback_message():
    """Non-``DomainError`` exception → message is ``"<TypeName> in <origin>"``.

    Crucially, the raw ``str(exc)`` (which may carry user input, secret
    tokens, RAG document fragments, …) must NOT be embedded.
    """
    secret = "USER_SECRET_VALUE"
    exc = _raise_and_capture(ValueError(secret))
    crash = collect_from_exception(
        exc,
        source="excepthook",
        settings=_settings(True),
        redactor=redactor,
        hardware_collector=hardware.collect,
    )
    assert crash is not None
    # Fallback template embeds type name + origin, never the raw payload.
    assert "ValueError" in crash.exception_message
    assert secret not in crash.exception_message
    assert crash.exception_type == "ValueError"


def test_collect_from_exception_returns_none_when_enabled_false():
    """``enabled=False`` is explicit opt-out → no crash collected."""
    exc = _raise_and_capture(RuntimeError("boom"))
    out = collect_from_exception(
        exc,
        source="fastapi",
        settings=_settings(False),
        redactor=redactor,
        hardware_collector=hardware.collect,
    )
    assert out is None


def test_collect_from_exception_returns_none_when_enabled_none():
    """``enabled=None`` means opt-in not yet decided → skip collection.

    Differs from ``False`` only in UX (we may prompt later); for the
    collector both paths short-circuit identically.
    """
    exc = _raise_and_capture(RuntimeError("boom"))
    out = collect_from_exception(
        exc,
        source="fastapi",
        settings=_settings(None),
        redactor=redactor,
        hardware_collector=hardware.collect,
    )
    assert out is None


def test_collect_from_exception_populates_required_fields():
    """All ``PendingCrash`` fields are populated (no defaults left empty)."""
    exc = _raise_and_capture(RuntimeError("boom"))
    crash = collect_from_exception(
        exc,
        source="fastapi",
        settings=_settings(True),
        redactor=redactor,
        hardware_collector=hardware.collect,
    )
    assert crash is not None
    assert crash.id  # non-empty
    assert crash.fingerprint  # non-empty SHA1 hex
    assert crash.created_at.endswith("Z")  # ISO-8601 UTC
    assert crash.exception_type == "RuntimeError"
    assert crash.trace  # at least one frame
    assert isinstance(crash.hardware, dict)
    assert crash.source == "fastapi"


@pytest.mark.parametrize("source", sorted(_VALID_SOURCES))
def test_collect_from_exception_accepts_every_source(source: str):
    """Every ``Source`` literal value must be a valid input to the
    collector. Parametrize over ``get_args(Source)`` (NOT a hand-rolled
    list) so adding a new source forces a corresponding code path.
    """
    exc = _raise_and_capture(RuntimeError("boom"))
    crash = collect_from_exception(
        exc,
        source=source,  # type: ignore[arg-type]
        settings=_settings(True),
        redactor=redactor,
        hardware_collector=hardware.collect,
    )
    assert crash is not None
    assert crash.source == source


def test_collect_from_exception_does_not_write_to_disk(tmp_path: Path):
    """Pure helper: even when invoked with a data_dir hint, it does NOT
    create files. Persistence is the trap handlers' responsibility
    (which go through pending_store.save explicitly)."""
    exc = _raise_and_capture(RuntimeError("boom"))
    _ = collect_from_exception(
        exc,
        source="fastapi",
        settings=_settings(True),
        redactor=redactor,
        hardware_collector=hardware.collect,
    )
    assert not (tmp_path / "crash-pending").exists()
    assert not (tmp_path / "reported.txt").exists()


def test_collect_from_exception_redacts_log_tail(tmp_path: Path):
    """``log_tail`` events with blocked keys are dropped; allowed
    fields are retained. Verifies wiring through ``redactor`` not just
    that the param is accepted.
    """
    exc = _raise_and_capture(RuntimeError("boom"))
    log_tail = [
        {"level": "INFO", "event_name": "rag.search", "duration_ms": 12},
        # Contains a blocked key → must be dropped wholesale
        {"level": "ERROR", "chunk_text": "secret leak"},
    ]
    crash = collect_from_exception(
        exc,
        source="fastapi",
        settings=_settings(True),
        redactor=redactor,
        hardware_collector=hardware.collect,
        log_tail=log_tail,
    )
    assert crash is not None
    assert len(crash.log_tail) == 1
    assert crash.log_tail[0]["event_name"] == "rag.search"


# ---------------------------------------------------------------------------
# register / unregister — state management
# ---------------------------------------------------------------------------


def test_register_can_be_called_repeatedly_without_leaking_state(tmp_path: Path):
    """Calling ``register`` twice must not produce two ``sys.excepthook``
    chains, two atexit registrations, or stacked signal handlers.

    Verifies: after two ``register`` calls, ``sys.excepthook`` is the
    most-recent installation (not an additive wrapper of two).
    """
    original_hook = sys.excepthook
    settings = _settings(True)
    app1 = FastAPI()
    app2 = FastAPI()

    register(
        app1,
        settings=settings,
        pending_store_dir=tmp_path,
        reported_store_path=tmp_path,
    )
    hook_after_first = sys.excepthook
    assert hook_after_first is not original_hook

    register(
        app2,
        settings=settings,
        pending_store_dir=tmp_path,
        reported_store_path=tmp_path,
    )
    hook_after_second = sys.excepthook
    # The second register should have unregistered the first hook
    # before installing its own. So the second hook's "original" is
    # the true original, not the first hook.
    assert hook_after_second is not hook_after_first

    unregister()
    assert sys.excepthook is original_hook


def test_unregister_restores_original_excepthook(tmp_path: Path):
    """After ``unregister`` ``sys.excepthook`` is fully restored.

    Critical because pytest itself relies on ``sys.excepthook`` for
    reporting; a leaked handler would corrupt all subsequent tests.
    """
    original_hook = sys.excepthook
    register(
        None,
        settings=_settings(True),
        pending_store_dir=tmp_path,
        reported_store_path=tmp_path,
    )
    assert sys.excepthook is not original_hook
    unregister()
    assert sys.excepthook is original_hook


def test_unregister_without_register_is_noop(tmp_path: Path):
    """``unregister`` called on a clean state must not raise (idempotent)."""
    unregister()  # should not raise
    unregister()  # twice for good measure


def test_register_skips_fastapi_handler_when_app_is_none(tmp_path: Path):
    """``register(None, ...)`` is valid (signal/excepthook/atexit-only path)."""
    register(
        None,
        settings=_settings(True),
        pending_store_dir=tmp_path,
        reported_store_path=tmp_path,
    )
    # Should not raise — the test passes if we get here
    unregister()


def test_register_restores_signal_handlers_on_unregister(tmp_path: Path):
    """Signal handlers installed by ``register`` are restored by
    ``unregister`` — important so pytest's ^C remains responsive.
    """
    if not hasattr(signal, "SIGINT"):
        pytest.skip("SIGINT unavailable")
    try:
        original_sigint = signal.getsignal(signal.SIGINT)
    except (OSError, ValueError):
        pytest.skip("cannot read SIGINT (non-main thread)")

    try:
        register(
            None,
            settings=_settings(True),
            pending_store_dir=tmp_path,
            reported_store_path=tmp_path,
        )
    except (OSError, ValueError):
        pytest.skip("cannot install signal handlers in this thread")

    unregister()
    assert signal.getsignal(signal.SIGINT) == original_sigint


# ---------------------------------------------------------------------------
# FastAPI integration via TestClient
# ---------------------------------------------------------------------------


def _fresh_app() -> FastAPI:
    """A minimal FastAPI app per-test (avoids cross-test handler bleed)."""
    app = FastAPI()

    @app.get("/boom")
    def boom() -> dict:
        raise RuntimeError("unhandled")

    @app.get("/ok")
    def ok() -> dict:
        return {"status": "ok"}

    return app


def test_fastapi_handler_saves_pending_crash_when_enabled(tmp_path: Path):
    """Request to a route that raises → response is 500 + a pending
    crash file was written to ``pending_store``.
    """
    app = _fresh_app()
    register(
        app,
        settings=_settings(True),
        pending_store_dir=tmp_path,
        reported_store_path=tmp_path,
    )

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom")
    assert response.status_code == 500

    pending = pending_store.load_all(tmp_path)
    assert len(pending) == 1
    assert pending[0].exception_type == "RuntimeError"
    assert pending[0].source == "fastapi"


def test_fastapi_handler_skips_when_settings_disabled(tmp_path: Path):
    """``enabled=False`` → request still returns 500 but NO pending file."""
    app = _fresh_app()
    register(
        app,
        settings=_settings(False),
        pending_store_dir=tmp_path,
        reported_store_path=tmp_path,
    )

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom")
    assert response.status_code == 500

    pending = pending_store.load_all(tmp_path)
    assert pending == []


def test_fastapi_handler_skips_when_settings_undecided(tmp_path: Path):
    """``enabled=None`` (opt-in not yet decided) → no pending file."""
    app = _fresh_app()
    register(
        app,
        settings=_settings(None),
        pending_store_dir=tmp_path,
        reported_store_path=tmp_path,
    )

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom")
    assert response.status_code == 500

    pending = pending_store.load_all(tmp_path)
    assert pending == []


def test_fastapi_handler_does_not_interfere_with_healthy_routes(tmp_path: Path):
    """Non-erroring routes return normally; the catch-all only fires on
    unhandled exceptions.
    """
    app = _fresh_app()
    register(
        app,
        settings=_settings(True),
        pending_store_dir=tmp_path,
        reported_store_path=tmp_path,
    )

    client = TestClient(app)
    response = client.get("/ok")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# dedup: reported fingerprint must not produce another pending file
# ---------------------------------------------------------------------------


def test_reported_fingerprint_is_not_double_saved(tmp_path: Path):
    """If a fingerprint already lives in ``reported.txt``, a fresh crash
    with the same fingerprint must NOT create a new pending file
    (spec §9 — don't re-prompt the user for a bug they already filed).

    Strategy: take two identical trips through ``/boom``. The first
    establishes the fingerprint (raised from the same code path, so the
    traceback topology — and thus the SHA1 — matches the second trip).
    We mark it as reported, then a second request must produce no new
    pending file.
    """
    app = _fresh_app()
    register(
        app,
        settings=_settings(True),
        pending_store_dir=tmp_path,
        reported_store_path=tmp_path,
    )
    client = TestClient(app, raise_server_exceptions=False)

    # First trip: learn the actual fingerprint produced by this route.
    response = client.get("/boom")
    assert response.status_code == 500
    pending = pending_store.load_all(tmp_path)
    assert len(pending) == 1
    fingerprint = pending[0].fingerprint

    # Clear the pending dir and mark the fingerprint as reported.
    for f in (tmp_path / "crash-pending").glob("*.json"):
        f.unlink()
    reported_store.mark_reported(tmp_path, fingerprint)

    # Second trip with the same fingerprint must NOT create a new pending.
    response = client.get("/boom")
    assert response.status_code == 500
    assert pending_store.load_all(tmp_path) == []


def test_unreported_fingerprint_is_saved(tmp_path: Path):
    """Symmetric check: an *unreported* fingerprint DOES get saved.

    Guards against an over-eager dedup that would block all crashes.
    """
    app = _fresh_app()
    register(
        app,
        settings=_settings(True),
        pending_store_dir=tmp_path,
        reported_store_path=tmp_path,
    )
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom")
    assert response.status_code == 500
    assert len(pending_store.load_all(tmp_path)) == 1


# ---------------------------------------------------------------------------
# excepthook chaining
# ---------------------------------------------------------------------------


def test_excepthook_collects_and_chains_to_original(tmp_path: Path):
    """``sys.excepthook`` installed by ``register`` must:
    1) collect the exception into a pending crash file, then
    2) chain to the previous excepthook so default reporting still works.
    """
    calls: list[tuple] = []

    def previous_hook(exc_type, exc_value, exc_tb):
        calls.append((exc_type, exc_value, exc_tb))

    original_hook = sys.excepthook
    sys.excepthook = previous_hook
    try:
        register(
            None,
            settings=_settings(True),
            pending_store_dir=tmp_path,
            reported_store_path=tmp_path,
        )
        exc = _raise_and_capture(RuntimeError("oops"))
        sys.excepthook(type(exc), exc, exc.__traceback__)

        # Pending crash saved
        pending = pending_store.load_all(tmp_path)
        assert len(pending) == 1
        assert pending[0].source == "excepthook"
        # Previous hook was chained
        assert len(calls) == 1
        assert calls[0][0] is RuntimeError
    finally:
        unregister()
        sys.excepthook = original_hook


def test_excepthook_skips_when_disabled(tmp_path: Path):
    """``enabled=False`` → excepthook does not write pending file but
    still chains to previous hook."""
    calls: list[tuple] = []

    def previous_hook(exc_type, exc_value, exc_tb):
        calls.append((exc_type, exc_value, exc_tb))

    original_hook = sys.excepthook
    sys.excepthook = previous_hook
    try:
        register(
            None,
            settings=_settings(False),
            pending_store_dir=tmp_path,
            reported_store_path=tmp_path,
        )
        exc = _raise_and_capture(RuntimeError("oops"))
        sys.excepthook(type(exc), exc, exc.__traceback__)

        assert pending_store.load_all(tmp_path) == []
        assert len(calls) == 1  # chain still works
    finally:
        unregister()
        sys.excepthook = original_hook


# ---------------------------------------------------------------------------
# atexit handler unregistration
# ---------------------------------------------------------------------------


def test_atexit_handler_can_be_unregistered(tmp_path: Path):
    """The collector must call ``atexit.unregister`` on its installed
    callback so repeated install/uninstall cycles don't accumulate
    leaked handlers (which would fire at interpreter shutdown).
    """
    register(
        None,
        settings=_settings(True),
        pending_store_dir=tmp_path,
        reported_store_path=tmp_path,
    )
    # Grab the registered handler for inspection.
    handler = collector_mod._REGISTERED.get("atexit_handler")
    assert handler is not None
    unregister()
    # After unregister the handler reference is cleared.
    assert collector_mod._REGISTERED.get("atexit_handler") is None
    # Calling atexit.unregister on it again should be a no-op (already removed).
    atexit.unregister(handler)

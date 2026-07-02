"""Unified crash collector — traps integration + register/unregister API.

spec §4.1 / plan Sprint 3 Task 3.4.

This module funnels every crash detection trap into a single pipeline:

    raw exception
        │
        ▼
    ``collect_from_exception``   (pure: redactor + fingerprint + hardware)
        │
        ▼
    PendingCrash                  (returned by the pure helper)
        │
        ▼
    dedup against reported_store  (`is_reported(fingerprint)`)
        │
        ▼
    `pending_store.save`          (atomic write to ``data_dir/crash-pending/``)

Traps installed by ``register``:

- **FastAPI exception handler** for ``Exception`` (catch-all 5xx).
  Saves a pending crash then returns a generic ``500`` JSON. We
  intentionally never embed the exception message in the response body
  (spec §6.3 — only ``safe_message`` / type-name are external-safe).
- **``sys.excepthook``** for uncaught exceptions in the main process.
  Always *chains* to the previously installed hook so pytest /
  the default Python REPL reporter still fire.
- **``signal.signal``** for ``SIGTERM`` / ``SIGINT`` (and ``SIGBREAK`` on
  Windows). Treats signal-driven exits as abnormal: saves a crash with
  ``source="signal"`` then raises ``SystemExit(128 + signum)``.
- **``atexit.register``** as the last-line-of-defense. Inspects
  ``sys.exc_info()`` at interpreter shutdown; saves a crash only if an
  unhandled exception is in flight (the "the excepthook never fired"
  fallback).

Design notes (testability):

- ``register``/``unregister`` are module-level functions backed by a
  single process-global dict ``_REGISTERED``. This mirrors the
  process-global nature of ``sys.excepthook`` / signal / atexit
  (which can't be scoped per-app). A re-entrant lock guards the dict
  so the test suite (or a misbehaving caller) can't tear down a
  half-installed state.
- Each ``register`` call first runs ``_do_unregister`` so repeated
  installs don't accumulate handler chains (spec lesson:
  "register/unregister can be called repeatedly without leaking state").
- ``atexit.unregister`` is called by name so ``unregister`` truly
  detaches our callback (not just a flag flip), preventing late firing
  during interpreter shutdown after the test suite has moved on.
"""
from __future__ import annotations

import atexit
import logging
import signal
import sys
import threading
import traceback
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.crash_reporter import (
    hardware as _hardware_module,
)
from core.crash_reporter import (
    pending_store,
    reported_store,
)
from core.crash_reporter import (
    redactor as _redactor_module,
)
from core.crash_reporter.fingerprint import compute_fingerprint
from core.crash_reporter.pending_store import PendingCrash, Source
from core.crash_reporter.settings import CrashReportSettings
from core.exceptions import safe_message_for

logger = logging.getLogger(__name__)

# Process-global state. Module-level because signal / atexit / sys.excepthook
# all are themselves process-global — there is no per-instance scope to
# attach this to. RLock to keep ``register``→``_do_unregister``→``register``
# (re-entrant install) deadlock-free.
_STATE_LOCK = threading.RLock()
_REGISTERED: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# pure helper
# ---------------------------------------------------------------------------


def _now_iso_utc() -> str:
    """UTC time as ``YYYY-MM-DDTHH:MM:SSZ`` (matches pending_store fixture)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_traceback(exc: BaseException) -> list[str]:
    """Return traceback lines for ``exc``. Falls back to a single-line
    ``Type: msg`` if ``__traceback__`` is unset (which happens for
    freshly-constructed exceptions that were never raised)."""
    tb = exc.__traceback__
    if tb is None:
        # No frames available — minimum viable info.
        cls = type(exc)
        return [f"{cls.__module__}.{cls.__qualname__}\n"]
    return traceback.format_exception(type(exc), exc, tb)


def collect_from_exception(
    exc: BaseException,
    *,
    source: Source,
    settings: CrashReportSettings,
    redactor: Any,
    hardware_collector: Callable[..., dict],
    log_tail: list[dict] | None = None,
    app_root: Path | None = None,
    data_dir: Path | None = None,
) -> PendingCrash | None:
    """Build a :class:`PendingCrash` from an exception (pure helper).

    Pure in the sense that it performs **no disk writes** — the caller
    is responsible for persisting via ``pending_store.save``. Hardware
    collection itself reads OS state (``psutil`` / ``nvidia-smi``) but
    does not mutate the project's data dir.

    Args:
        exc: the exception to dossier.
        source: one of :data:`pending_store.Source`.
        settings: user opt-in settings. Returns ``None`` unless
            ``settings.enabled is True``.
        redactor: module-like object exposing ``redact_traceback`` and
            ``redact_log_event``. Injected for test substitutability;
            production wiring passes :mod:`core.crash_reporter.redactor`.
        hardware_collector: callable returning the hardware snapshot
            dict. Production wiring is ``hardware.collect``.
        log_tail: optional list of structured log events to attach,
            after redaction.
        app_root: root path used by ``redact_traceback`` to decide which
            frames to keep verbatim (defaults to CWD).
        data_dir: hint passed to ``hardware.collect`` so disk-free is
            probed on the right drive (not strictly needed; falls back
            to HOME if unset).

    Returns:
        ``None`` if collection is suppressed by the opt-in gate, else a
        fully-populated :class:`PendingCrash`.
    """
    # Opt-in gate. ``enabled`` is tri-state (True / False / None).
    # None means "user has not yet decided" → do NOT collect (spec §7.3).
    if settings.enabled is not True:
        return None

    cls = type(exc)
    origin = f"{cls.__module__}.{cls.__qualname__}"
    # safe_message_for: DomainError → safe_message, else "<Type> in <origin>".
    # NEVER use ``str(exc)`` here — that may carry user-supplied or
    # RAG-document text which spec §6.3 forbids leaking.
    exc_msg = safe_message_for(exc, origin=origin)
    exc_type = cls.__qualname__

    # Traceback collection + redaction. ``app_root`` keeps app frames
    # verbatim and replaces HOME with ``<HOME>``.
    tb_lines = _format_traceback(exc)
    if app_root is None:
        app_root = Path.cwd()
    redact_tb = getattr(redactor, "redact_traceback", None)
    if redact_tb is not None:
        try:
            tb_lines = redact_tb(tb_lines, Path(app_root))
        except Exception:
            logger.exception("crash_collector: redact_traceback failed; keeping raw")

    # Hardware snapshot (best-effort; failures fall through to empty dict).
    hw: dict = {}
    try:
        # Production ``hardware.collect`` accepts an optional ``data_dir``.
        # Tests sometimes inject a callable that takes no args — handle both.
        try:
            hw = hardware_collector(data_dir)
        except TypeError:
            hw = hardware_collector()
    except Exception:
        logger.exception("crash_collector: hardware_collector failed; emitting empty")
        hw = {}

    # Log tail redaction. Events containing a blocked key (anywhere in
    # the nested structure) are dropped entirely (``redact_log_event`` →
    # ``None``).
    redacted_log_tail: list[dict] = []
    if log_tail:
        redact_event = getattr(redactor, "redact_log_event", None)
        if redact_event is None:
            redacted_log_tail = list(log_tail)
        else:
            for event in log_tail:
                try:
                    cleaned = redact_event(event)
                except Exception:
                    cleaned = None
                if cleaned is not None:
                    redacted_log_tail.append(cleaned)

    fingerprint = compute_fingerprint(exc)
    crash_id = uuid.uuid4().hex

    return PendingCrash(
        id=crash_id,
        fingerprint=fingerprint,
        created_at=_now_iso_utc(),
        exception_type=exc_type,
        exception_message=exc_msg,
        trace=tb_lines,
        hardware=hw,
        log_tail=redacted_log_tail,
        source=source,
    )


# ---------------------------------------------------------------------------
# internal: gated save (used by all trap handlers)
# ---------------------------------------------------------------------------


def _collect_and_save(exc: BaseException, *, source: Source) -> PendingCrash | None:
    """Trap-handler entry point: build a crash + dedup + persist.

    Called by the FastAPI handler / excepthook / signal handler /
    atexit handler. Reads its inputs from the process-global
    ``_REGISTERED`` dict so each individual handler can stay
    parameterless (signal handler signature is fixed by the OS API,
    excepthook signature is fixed by ``sys``).
    """
    state = _REGISTERED
    settings: CrashReportSettings | None = state.get("settings")
    if settings is None:
        # Defensive: handler fired after unregister. Bail.
        return None

    pending_dir: Path | None = state.get("pending_store_dir")
    reported_dir: Path | None = state.get("reported_store_path")
    app_root: Path | None = state.get("app_root")
    if pending_dir is None or reported_dir is None:
        return None

    crash = collect_from_exception(
        exc,
        source=source,
        settings=settings,
        redactor=_redactor_module,
        hardware_collector=_hardware_module.collect,
        app_root=app_root,
        data_dir=pending_dir,
    )
    if crash is None:
        return None

    # Dedup: if the user has already filed this fingerprint, don't pile
    # up another pending file (spec §9 — no re-prompting for known bugs).
    if reported_store.is_reported(reported_dir, crash.fingerprint):
        return None

    try:
        pending_store.save(pending_dir, crash)
    except Exception:
        logger.exception("crash_collector: failed to save pending crash %s", crash.id)
        return None
    return crash


# ---------------------------------------------------------------------------
# trap installers
# ---------------------------------------------------------------------------


def _make_fastapi_handler() -> Callable[[Request, Exception], Any]:
    """Build the FastAPI exception handler closure.

    Returns a coroutine function: FastAPI dispatches both sync and async
    handlers, but coroutine form keeps integration with starlette
    cleaner and matches the existing ``app_error_handler`` style in
    ``apps/api/main.py``.
    """

    async def _fastapi_handler(_request: Request, exc: Exception) -> JSONResponse:
        try:
            _collect_and_save(exc, source="fastapi")
        except Exception:
            logger.exception("crash_collector: fastapi handler swallowed error")
        # Spec §6.3: never echo the raw exception message.
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal",
                    "message": "internal server error",
                }
            },
        )

    return _fastapi_handler


def _install_fastapi(app: FastAPI | None) -> None:
    if app is None:
        return
    handler = _make_fastapi_handler()
    app.add_exception_handler(Exception, handler)
    _REGISTERED["fastapi_app"] = app
    _REGISTERED["fastapi_handler"] = handler


def _install_excepthook() -> None:
    """Install a chaining ``sys.excepthook``.

    The original hook is preserved so we can:
    1) invoke it AFTER our collection (default reporter still fires), and
    2) restore it cleanly in ``unregister``.
    """
    previous_hook = sys.excepthook

    def _excepthook(
        exc_type: type[BaseException],
        exc_value: BaseException | None,
        exc_tb: Any,
    ) -> None:
        if exc_value is not None:
            try:
                _collect_and_save(exc_value, source="excepthook")
            except Exception:
                logger.exception("crash_collector: excepthook swallowed error")
        # Always chain — losing the original handler would silently break
        # Python's default crash reporting (and pytest's failure print).
        try:
            previous_hook(exc_type, exc_value, exc_tb)
        except Exception:
            logger.exception("crash_collector: previous excepthook raised")

    sys.excepthook = _excepthook
    _REGISTERED["original_excepthook"] = previous_hook
    _REGISTERED["excepthook"] = _excepthook


def _install_signal_handlers() -> None:
    """Install signal handlers for SIGTERM/SIGINT (and SIGBREAK on Windows).

    Signals fire asynchronously and on the main thread only. We capture
    the previous handler per-signal for restoration in ``unregister``.
    If we can't install (e.g. running on a worker thread per
    ``ValueError``), we silently skip that signal — collection just
    won't fire on signal-driven exits in that thread, which is
    acceptable degradation (the FastAPI / excepthook paths still cover
    the dominant crash classes).
    """
    originals: dict[int, Any] = {}
    sig_names = ("SIGTERM", "SIGINT", "SIGBREAK")
    for name in sig_names:
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            original = signal.getsignal(sig)
        except (OSError, ValueError):
            continue

        def _handler(signum: int, _frame: Any, _name: str = name) -> None:
            try:
                # Signals are inherently lossy — we synthesise a
                # KeyboardInterrupt-shaped exception to feed the
                # collector pipeline. ``source="signal"`` distinguishes
                # this from a user-thrown KeyboardInterrupt that takes
                # the excepthook path.
                exc = KeyboardInterrupt(f"signal={_name}")
                _collect_and_save(exc, source="signal")
            except Exception:
                logger.exception("crash_collector: signal handler swallowed error")
            raise SystemExit(128 + int(signum))

        try:
            signal.signal(sig, _handler)
        except (OSError, ValueError, TypeError):
            # Non-main thread or unsupported signal — degrade silently.
            continue
        originals[int(sig)] = original
    _REGISTERED["original_signals"] = originals


def _install_atexit() -> None:
    """Install the atexit "last-line-of-defense" handler.

    Only saves a crash if an exception is in flight at interpreter
    shutdown — otherwise the excepthook would have handled it already.
    """

    def _atexit_handler() -> None:
        if not _REGISTERED.get("atexit_enabled"):
            return
        _exc_type, exc_value, _exc_tb = sys.exc_info()
        if exc_value is None:
            return  # clean shutdown sentinel — nothing to collect
        try:
            _collect_and_save(exc_value, source="atexit")
        except Exception:
            logger.exception("crash_collector: atexit handler swallowed error")

    atexit.register(_atexit_handler)
    _REGISTERED["atexit_handler"] = _atexit_handler
    _REGISTERED["atexit_enabled"] = True


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def register(
    app: FastAPI | None,
    *,
    settings: CrashReportSettings,
    pending_store_dir: Path,
    reported_store_path: Path,
    app_root: Path | None = None,
) -> None:
    """Install all crash traps (FastAPI + excepthook + signal + atexit).

    Calling ``register`` while already registered first detaches the
    previous installation (no chained leaks, no duplicate atexit
    callbacks, no stacked signal handlers).

    Args:
        app: a :class:`FastAPI` instance to attach the catch-all handler
            to, or ``None`` for non-HTTP scenarios (CLI scripts, tests
            that only exercise the excepthook path).
        settings: the user opt-in settings. Read on every trap firing
            so toggling it at runtime (e.g. user opts out mid-session)
            takes effect immediately.
        pending_store_dir: data dir for ``pending_store.save``. Pending
            crashes land under ``pending_store_dir/crash-pending/``.
        reported_store_path: data dir for ``reported_store.is_reported``.
            Lives at ``reported_store_path/reported.txt``. Often the same
            as ``pending_store_dir`` but separated in the signature so
            tests can isolate them.
        app_root: project root used by ``redact_traceback`` to keep
            application frames verbatim. Defaults to CWD.
    """
    with _STATE_LOCK:
        # Always tear down first so a second call doesn't pile up state.
        _do_unregister()

        _REGISTERED["settings"] = settings
        _REGISTERED["pending_store_dir"] = Path(pending_store_dir)
        _REGISTERED["reported_store_path"] = Path(reported_store_path)
        _REGISTERED["app_root"] = Path(app_root) if app_root is not None else Path.cwd()

        _install_fastapi(app)
        _install_excepthook()
        _install_signal_handlers()
        _install_atexit()


def unregister() -> None:
    """Remove every trap installed by ``register`` (idempotent).

    Safe to call before any ``register`` (no-op on clean state). Safe to
    call multiple times.
    """
    with _STATE_LOCK:
        _do_unregister()


def _do_unregister() -> None:
    """Internal: actually detach handlers. Caller holds ``_STATE_LOCK``."""
    # FastAPI: starlette exposes ``app.exception_handlers`` as a plain
    # dict so we just delete our entry if it's still present.
    fastapi_app: FastAPI | None = _REGISTERED.pop("fastapi_app", None)
    fastapi_handler = _REGISTERED.pop("fastapi_handler", None)
    if fastapi_app is not None and fastapi_handler is not None:
        try:
            if fastapi_app.exception_handlers.get(Exception) is fastapi_handler:
                del fastapi_app.exception_handlers[Exception]
        except (AttributeError, KeyError):
            # Starlette version drift — best-effort cleanup.
            pass

    # sys.excepthook
    original_hook = _REGISTERED.pop("original_excepthook", None)
    _REGISTERED.pop("excepthook", None)
    if original_hook is not None:
        sys.excepthook = original_hook

    # signal handlers
    originals: dict[int, Any] = _REGISTERED.pop("original_signals", {})
    for signum, original in originals.items():
        try:
            sig = signal.Signals(signum)
        except ValueError:
            sig = signum  # raw int still accepted by signal.signal
        try:
            if original is None or original is signal.SIG_DFL:
                signal.signal(sig, signal.SIG_DFL)
            elif original is signal.SIG_IGN:
                signal.signal(sig, signal.SIG_IGN)
            else:
                signal.signal(sig, original)
        except (OSError, ValueError, TypeError):
            pass

    # atexit
    atexit_handler = _REGISTERED.pop("atexit_handler", None)
    _REGISTERED["atexit_enabled"] = False
    if atexit_handler is not None:
        try:
            atexit.unregister(atexit_handler)
        except Exception:
            logger.debug("crash_collector: atexit.unregister failed (handler likely already gone)")

    # context
    _REGISTERED.pop("settings", None)
    _REGISTERED.pop("pending_store_dir", None)
    _REGISTERED.pop("reported_store_path", None)
    _REGISTERED.pop("app_root", None)


__all__ = [
    "collect_from_exception",
    "register",
    "unregister",
]

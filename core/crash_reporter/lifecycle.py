"""Process-lifetime tracking for unclean shutdown detection.

spec §4.1 ④ / §7.2, plan Sprint 4 Task 4.2.

This module owns ``running.lock`` — a single file under the data dir
holding the PID of the uvicorn process that currently "owns" the data
dir. The contract is:

* On startup, :func:`acquire` is called. If the lock already exists and
  the PID inside is dead (per ``psutil.pid_exists``), the previous
  session crashed without releasing the lock; the function returns an
  :class:`UncleanShutdown` so the caller can ingest the rotated
  ``last-session.log.prev`` for forensic context. In *all* cases — alive
  prior PID, dead prior PID, no prior lock at all — the lock is
  overwritten atomically with the current PID.
* On shutdown, :func:`release` removes the lock. The next startup will
  then see no lock and conclude "clean prior shutdown".

We deliberately do **not** treat a live prior PID as a crash: this is
the dominant case under ``uvicorn --reload`` (the previous worker is
still up while the new one boots and races for the lock). Treating
that race as a crash would generate spurious reports on every code
reload during development.

:func:`collect_pending_from_log_tail` is the companion ingestion path
that turns the rotated log into a :class:`pending_store.PendingCrash`
JSON file with ``source="unclean_shutdown"``, gated by the user's
opt-in and by the dedup ``reported_store``.

Design notes:

- ``psutil`` is an *optional* import. On hosts without it, we cannot
  prove a prior PID is dead, so we conservatively assume **alive** and
  return ``None``. The trade-off is "miss some unclean shutdowns" vs
  "spam the user on every reload"; the latter is intolerable, so we
  err on the side of silence.
- Lock writes go through a ``.tmp`` + ``os.replace`` dance so a power
  loss or interpreter kill mid-write cannot leave a partially-written
  lock that would later parse as a different PID (or fail to parse).
  The companion ``.tmp`` file is cleaned up on rename failure so it
  cannot accumulate.
- Fingerprinting from log-tail data is necessarily lossy: the redacted
  log has no stack frames, so we hash the surviving exception type +
  module + event name. Two unclean shutdowns from the same code path
  collide (deduped, as desired); two unclean shutdowns from the same
  exception type at different sites usually do not (because event_name
  differs).
"""
from __future__ import annotations

import hashlib
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.crash_reporter import pending_store, reported_store
from core.crash_reporter.pending_store import PendingCrash
from core.crash_reporter.settings import CrashReportSettings
from core.logging import tail_last_session

# Optional psutil — see module docstring for the "cannot prove dead"
# trade-off when it is missing.
try:
    import psutil as _psutil  # type: ignore
except ImportError:  # pragma: no cover — psutil is in pyproject deps
    _psutil = None


logger = logging.getLogger(__name__)

# How many log lines from the tail we consider when sniffing the last
# ERROR event. Matches spec §7.2 reference ("lines=100").
_TAIL_LINES = 100

# Conventional filename of the rotated previous session log. Mirrors
# ``core.logging._PREV_SESSION_FILENAME`` but kept private to that
# module; we duplicate the constant rather than importing a private
# symbol so the dependency stays one-way (lifecycle -> logging via
# the public ``tail_last_session``).
_PREV_LOG_FILENAME = "last-session.log.prev"


@dataclass(frozen=True)
class UncleanShutdown:
    """Signal returned by :func:`acquire` when the prior PID is dead.

    Attributes:
        previous_pid: The dead PID we read out of the stale lock. Useful
            for log correlation when investigating the crash.
        prev_log_path: Conventional location of the rotated session log
            (``<data_dir>/logs/last-session.log.prev``). May not exist
            yet — :func:`collect_pending_from_log_tail` tolerates that.
    """

    previous_pid: int
    prev_log_path: Path


# ---------------------------------------------------------------------------
# psutil shim
# ---------------------------------------------------------------------------


def _is_pid_alive(pid: int) -> bool:
    """Return ``True`` if ``pid`` is currently running on this host.

    Falls back to "assume alive" when psutil is unavailable so callers
    do not falsely classify a clean prior shutdown as a crash — the
    only failure mode of returning True for a dead PID is "miss the
    unclean-shutdown report", which is preferable to spamming the user
    on every uvicorn reload.
    """
    if _psutil is None:
        return True
    try:
        return bool(_psutil.pid_exists(int(pid)))
    except Exception:
        logger.debug("lifecycle: psutil.pid_exists raised; assuming alive", exc_info=True)
        return True


# ---------------------------------------------------------------------------
# lock file I/O
# ---------------------------------------------------------------------------


def _atomic_write_lock(lock_path: Path, pid: int) -> None:
    """Write ``pid`` to ``lock_path`` atomically.

    Strategy: write to ``<lock>.tmp``, fsync, then ``os.replace`` onto
    the real path. ``os.replace`` is atomic on POSIX *and* Windows
    (NTFS), so a reader either sees the prior contents or the new ones,
    never a torn write. If ``os.replace`` raises (the test suite forces
    this), the ``.tmp`` companion is cleaned up so it cannot accumulate
    across retries.
    """
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = lock_path.with_suffix(lock_path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(str(int(pid)))
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # Some filesystems (e.g. certain network mounts) cannot
                # fsync — durability is best-effort, not load-bearing.
                pass
        os.replace(tmp, lock_path)
    except BaseException:
        # Replace failed — make sure we don't leave a stale ``.tmp``
        # behind. The original ``lock_path`` is untouched because
        # ``os.replace`` either succeeds atomically or doesn't fire.
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise


def _read_lock_pid(lock_path: Path) -> int | None:
    """Return the PID stored in ``lock_path`` or ``None`` if the file
    is missing / unreadable / contains non-integer junk.

    A garbage lock is treated the same as a missing lock: we cannot
    prove a prior crash without a parseable PID, and false positives
    are more harmful than false negatives.
    """
    try:
        text = Path(lock_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        return int(text.strip())
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def acquire(running_lock_path: Path, pid: int | None = None) -> UncleanShutdown | None:
    """Stamp our PID into the lock; report unclean shutdown if applicable.

    Args:
        running_lock_path: Absolute path to ``running.lock`` (typically
            ``config.running_lock_path``).
        pid: Optional explicit PID to write. Defaults to ``os.getpid()``.
            Tests use this to pin a deterministic value; a launcher
            wrapping a child uvicorn process could pass the child PID.

    Returns:
        :class:`UncleanShutdown` if the prior session's PID is no longer
        alive (caller should ingest ``last-session.log.prev``). ``None``
        in every other case: no prior lock, prior PID still alive
        (``uvicorn --reload`` race), garbage lock contents, or psutil
        unavailable.

    Side effects:
        Always writes the current PID into ``running_lock_path`` via an
        atomic ``.tmp`` + ``os.replace``. Creates parent directories
        as needed (fresh-install path).
    """
    running_lock_path = Path(running_lock_path)
    if pid is None:
        pid = os.getpid()

    result: UncleanShutdown | None = None
    if running_lock_path.exists():
        prev_pid = _read_lock_pid(running_lock_path)
        if prev_pid is not None and not _is_pid_alive(prev_pid):
            # By convention the rotated log lives at
            # ``<data_dir>/logs/last-session.log.prev``. The lock lives
            # at ``<data_dir>/running.lock``, so the data_dir is the
            # lock's parent. We hand the caller the conventional path
            # even if the file does not exist — they decide what to do.
            data_dir = running_lock_path.parent
            prev_log_path = data_dir / "logs" / _PREV_LOG_FILENAME
            result = UncleanShutdown(previous_pid=prev_pid, prev_log_path=prev_log_path)

    _atomic_write_lock(running_lock_path, pid)
    return result


def release(running_lock_path: Path) -> None:
    """Remove the running lock (idempotent on a missing file).

    The lifespan ``finally`` block relies on idempotency: if startup
    bailed before :func:`acquire` ran, ``release`` must still be safe
    to call.
    """
    try:
        Path(running_lock_path).unlink()
    except FileNotFoundError:
        return
    except OSError:
        # Permission error / locked-by-another-process — best effort.
        logger.debug("lifecycle: release() could not unlink lock", exc_info=True)


# ---------------------------------------------------------------------------
# log-tail ingestion
# ---------------------------------------------------------------------------


def _fingerprint_from_event(event: dict) -> str:
    """SHA1 of (exception module/type + event name) from a redacted log
    event.

    We *cannot* fingerprint from stack frames here because the file
    sink in :mod:`core.logging` strips them (only whitelisted fields
    survive). The next best thing is the combination of exception
    origin + the structured event name where the failure surfaced —
    same code path through the same handler will collide, which is the
    intent for dedup.
    """
    exc_type = str(event.get("exception_type") or "UnknownError")
    exc_module = str(event.get("exception_module") or "unknown")
    event_name = str(event.get("event_name") or "unknown")
    payload = f"unclean_shutdown::{exc_module}.{exc_type}::{event_name}"
    # Not used for security — only for dedup fingerprinting.
    return hashlib.sha1(payload.encode("utf-8"), usedforsecurity=False).hexdigest()


def _now_iso_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _events_via_tail_helper(prev_log_path: Path) -> list[dict]:
    """Read & parse the rotated log via the public Task 4.1 helper.

    :func:`core.logging.tail_last_session` is hard-coded to look at
    ``<data_dir>/logs/last-session.log.prev``. The lifecycle layout
    guarantees ``prev_log_path == data_dir / "logs" / "last-session.log.prev"``,
    so the helper's expected ``data_dir`` is two levels up.
    """
    # Layout: prev_log_path = data_dir / logs / last-session.log.prev
    # parent      = logs/
    # parent.parent = data_dir
    return tail_last_session(prev_log_path.parent.parent, lines=_TAIL_LINES)


def collect_pending_from_log_tail(
    prev_log_path: Path,
    data_dir: Path,
    settings: CrashReportSettings,
) -> int:
    """Build a :class:`PendingCrash` from the last ERROR-level event.

    Args:
        prev_log_path: Path to ``last-session.log.prev`` (the rotated
            log from the previous session). Must follow the layout
            ``<data_dir>/logs/last-session.log.prev`` for the helper to
            find it.
        data_dir: Application data dir — used for the pending store
            (``crash-pending/``) and the reported-fingerprint dedup
            (``reported.txt``). Often the same as ``prev_log_path``'s
            grandparent, but the signature keeps them separate so test
            suites can isolate them.
        settings: User opt-in settings. ``enabled is not True`` (i.e.
            ``False`` *or* ``None``) short-circuits to ``0``.

    Returns:
        ``1`` if a new pending crash was written, ``0`` otherwise.
        Zero is returned for any of: opted out, prev log missing,
        prev log has no ERROR-level events, fingerprint already
        reported, or save failed.
    """
    if settings.enabled is not True:
        return 0

    prev_log_path = Path(prev_log_path)
    data_dir = Path(data_dir)

    if not prev_log_path.is_file():
        return 0

    try:
        events = _events_via_tail_helper(prev_log_path)
    except Exception:
        logger.exception("lifecycle: failed to tail prev log")
        return 0

    if not events:
        return 0

    # Most recent ERROR event drives the crash — it is the closest in
    # time to the actual termination. Walk the tail in reverse so the
    # search terminates as soon as we find one.
    error_event: dict | None = None
    for ev in reversed(events):
        level = str(ev.get("level", "")).upper()
        if level == "ERROR":
            error_event = ev
            break

    if error_event is None:
        return 0

    fingerprint = _fingerprint_from_event(error_event)
    if reported_store.is_reported(data_dir, fingerprint):
        return 0

    exc_type = str(error_event.get("exception_type") or "UncleanShutdown")
    exc_module = str(error_event.get("exception_module") or "unknown")

    crash = PendingCrash(
        id=uuid.uuid4().hex,
        fingerprint=fingerprint,
        created_at=_now_iso_utc(),
        # Mirror the safe_message_for fallback shape used by the live
        # collector: "<Type> in <module>". We append a marker so the
        # GitHub issue body makes it obvious this is a post-mortem
        # reconstruction, not a freshly-caught exception.
        exception_type=exc_type,
        exception_message=f"{exc_type} in {exc_module} (unclean shutdown)",
        trace=[],  # redacted away by the file sink — none to recover
        hardware={},  # captured at *report* time, not at unclean exit
        log_tail=list(events),
        source="unclean_shutdown",
    )

    try:
        pending_store.save(data_dir, crash)
    except Exception:
        logger.exception("lifecycle: failed to save unclean-shutdown pending crash")
        return 0
    return 1


__all__ = [
    "UncleanShutdown",
    "acquire",
    "collect_pending_from_log_tail",
    "release",
]

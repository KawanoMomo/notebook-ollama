"""Tests for ``core.crash_reporter.lifecycle``.

spec §4.1 ④ / §7.2, plan Sprint 4 Task 4.2.

Covers:

- ``acquire``: writes a fresh ``running.lock`` for the current PID and,
  when a stale lock from a dead PID is present, surfaces a
  :class:`UncleanShutdown` so the caller can ingest the prior session's
  log. A live PID in the lock is treated as ``uvicorn --reload`` and
  produces no ``UncleanShutdown``.
- ``release``: deletes the lock (and is idempotent on a missing file).
- ``collect_pending_from_log_tail``: parses the rotated
  ``last-session.log.prev`` via :func:`core.logging.tail_last_session`,
  extracts the last ERROR-level event, builds a :class:`PendingCrash`
  with ``source="unclean_shutdown"``, and writes it through
  :mod:`core.crash_reporter.pending_store` — but only when its
  fingerprint is not already in ``reported.txt``.
- Atomic lock write: a simulated ``os.replace`` failure must leave the
  prior lock contents intact (the ``.tmp`` companion is the one that
  may be partial).

Design notes:

- We avoid spawning real processes for the "dead PID" test by using a
  PID that ``psutil.pid_exists`` is overwhelmingly likely to reject
  (a very large integer well above the system PID space). For the
  "alive PID" test we use ``os.getpid()`` which is guaranteed alive.
- We clear ``reported_store._CACHE`` between tests so the dedup test
  cannot be poisoned by a prior ``tmp_path`` whose absolute path
  happens to alias.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core.crash_reporter import (
    lifecycle,
    pending_store,
    reported_store,
)
from core.crash_reporter.lifecycle import (
    UncleanShutdown,
    acquire,
    collect_pending_from_log_tail,
    release,
)
from core.crash_reporter.settings import CrashReportSettings

# A PID that is overwhelmingly unlikely to exist on any sane host.
# Linux default kernel.pid_max is 4_194_304; Windows PIDs are 32-bit but
# the OS never hands out values this large in practice. ``psutil.pid_exists``
# returns False for unused PIDs without raising.
_GHOST_PID = 2_147_000_000


@pytest.fixture(autouse=True)
def _reset_reported_store_cache() -> None:
    """Clear the in-process reported_store cache so each test sees a
    fresh tmp_path without bleed from prior runs."""
    reported_store._CACHE.clear()
    yield
    reported_store._CACHE.clear()


def _write_log_lines(prev_log_path: Path, events: list[dict]) -> None:
    """Write a fake rotated last-session.log.prev (JSON lines)."""
    prev_log_path.parent.mkdir(parents=True, exist_ok=True)
    with prev_log_path.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False))
            f.write("\n")


# ---------------------------------------------------------------------------
# acquire / release
# ---------------------------------------------------------------------------


def test_acquire_with_no_existing_lock_writes_current_pid(tmp_path: Path):
    """First-time acquire on a clean directory must (a) return no
    ``UncleanShutdown`` (nothing to recover) and (b) write the current
    PID into ``running.lock``.
    """
    lock = tmp_path / "running.lock"
    assert not lock.exists()

    result = acquire(lock)

    assert result is None
    assert lock.is_file()
    assert lock.read_text(encoding="utf-8").strip() == str(os.getpid())


def test_acquire_uses_explicit_pid_when_provided(tmp_path: Path):
    """``acquire`` accepts an explicit ``pid`` so a launcher script can
    record a child uvicorn PID rather than its own (and so tests can
    pin a deterministic value)."""
    lock = tmp_path / "running.lock"
    acquire(lock, pid=12345)
    assert lock.read_text(encoding="utf-8").strip() == "12345"


def test_acquire_with_dead_pid_returns_unclean_shutdown(tmp_path: Path):
    """If the prior PID is dead, acquire returns an :class:`UncleanShutdown`
    pointing the caller at ``logs/last-session.log.prev`` for ingestion.

    The new lock is still written with the current PID so the next
    startup sees this session, not the dead one.
    """
    lock = tmp_path / "running.lock"
    lock.write_text(str(_GHOST_PID), encoding="utf-8")

    result = acquire(lock)

    assert isinstance(result, UncleanShutdown)
    assert result.previous_pid == _GHOST_PID
    # The path it hands us is the conventional rotated log location,
    # whether or not the file exists yet. The caller decides what to do
    # if it's missing.
    assert result.prev_log_path == tmp_path / "logs" / "last-session.log.prev"
    # Lock has been overwritten with our PID, ready for this session.
    assert lock.read_text(encoding="utf-8").strip() == str(os.getpid())


def test_acquire_with_alive_pid_returns_none_and_overwrites_lock(tmp_path: Path):
    """A live PID in the lock looks like a ``uvicorn --reload`` restart
    (or, very rarely, a true concurrent run). Either way we suppress
    the unclean-shutdown signal — re-reporting on every reload would
    be intolerable — and just stamp the lock with our PID."""
    lock = tmp_path / "running.lock"
    alive_pid = os.getpid()
    lock.write_text(str(alive_pid), encoding="utf-8")

    result = acquire(lock)

    assert result is None
    assert lock.read_text(encoding="utf-8").strip() == str(os.getpid())


def test_acquire_with_garbage_lock_contents_treats_as_no_prior(tmp_path: Path):
    """A corrupted lock (non-integer text) is indistinguishable from
    "no prior session" — we cannot prove a crash without a parseable
    PID, so we conservatively skip the unclean-shutdown path."""
    lock = tmp_path / "running.lock"
    lock.write_text("not-a-pid", encoding="utf-8")

    result = acquire(lock)

    assert result is None
    assert lock.read_text(encoding="utf-8").strip() == str(os.getpid())


def test_release_removes_existing_lock(tmp_path: Path):
    """Normal release path: lock file goes away."""
    lock = tmp_path / "running.lock"
    lock.write_text(str(os.getpid()), encoding="utf-8")

    release(lock)

    assert not lock.exists()


def test_release_is_idempotent_on_missing_path(tmp_path: Path):
    """``release`` called on a path that was never acquired (or was
    already cleaned up) must not raise — the lifespan ``finally`` block
    relies on this."""
    lock = tmp_path / "running.lock"
    assert not lock.exists()
    release(lock)  # no error
    release(lock)  # second call also no error
    assert not lock.exists()


def test_acquire_creates_parent_dir(tmp_path: Path):
    """The data_dir may not yet exist on first launch (fresh install).
    ``acquire`` should mkdir parents rather than crash."""
    lock = tmp_path / "new" / "nested" / "running.lock"
    assert not lock.parent.exists()

    result = acquire(lock)

    assert result is None
    assert lock.is_file()


# ---------------------------------------------------------------------------
# atomic write resilience
# ---------------------------------------------------------------------------


def test_acquire_atomic_write_failure_preserves_original_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """If ``os.replace`` fails midway through stamping our PID, the
    *prior* lock contents must survive untouched. Otherwise an
    interrupted write could blank the lock and we would lose the
    previous PID we needed to detect the unclean shutdown next time.
    """
    lock = tmp_path / "running.lock"
    lock.write_text("99999", encoding="utf-8")
    original_bytes = lock.read_bytes()

    def _boom(src, dst):
        raise OSError("simulated atomic rename failure")

    monkeypatch.setattr(lifecycle.os, "replace", _boom)

    with pytest.raises(OSError, match="simulated atomic rename"):
        # We patched at module level; the prior PID 99999 is dead per
        # _GHOST_PID semantics, so the code path would normally
        # construct an UncleanShutdown and then write — the write is
        # what blows up here.
        acquire(lock)

    # Lock unchanged: still the original "99999" bytes.
    assert lock.read_bytes() == original_bytes
    # No leaked ``.tmp`` companion.
    assert not (lock.parent / "running.lock.tmp").exists()


# ---------------------------------------------------------------------------
# collect_pending_from_log_tail
# ---------------------------------------------------------------------------


def _settings_enabled() -> CrashReportSettings:
    return CrashReportSettings(enabled=True)


def test_collect_pending_from_log_tail_creates_pending_for_error(tmp_path: Path):
    """A rotated log containing an ERROR-level event yields exactly one
    pending crash file with ``source="unclean_shutdown"``.

    The structured log has been redacted on the way in (Sprint 4 Task 4.1
    file sink), so only whitelisted fields are available. We synthesise
    a fingerprint from the surviving exception type / module / event
    name — enough for dedup, but the trace itself is necessarily lost.
    """
    prev_log = tmp_path / "logs" / "last-session.log.prev"
    _write_log_lines(
        prev_log,
        [
            {"level": "INFO", "event_name": "startup", "timestamp": "2026-06-28T00:00:00Z"},
            {
                "level": "ERROR",
                "event_name": "rag.search",
                "exception_type": "RuntimeError",
                "exception_module": "core.retrieval",
                "timestamp": "2026-06-28T00:01:00Z",
            },
        ],
    )

    count = collect_pending_from_log_tail(prev_log, tmp_path, _settings_enabled())

    assert count == 1
    pending = pending_store.load_all(tmp_path)
    assert len(pending) == 1
    crash = pending[0]
    assert crash.source == "unclean_shutdown"
    assert crash.exception_type == "RuntimeError"
    assert crash.fingerprint  # non-empty


def test_collect_pending_from_log_tail_picks_last_error_event(tmp_path: Path):
    """When multiple ERROR events exist, the *most recent* one drives the
    crash (it is the closest to the actual termination)."""
    prev_log = tmp_path / "logs" / "last-session.log.prev"
    _write_log_lines(
        prev_log,
        [
            {
                "level": "ERROR",
                "event_name": "early.failure",
                "exception_type": "ValueError",
                "exception_module": "core.early",
            },
            {"level": "INFO", "event_name": "recovered"},
            {
                "level": "ERROR",
                "event_name": "fatal.failure",
                "exception_type": "RuntimeError",
                "exception_module": "core.late",
            },
        ],
    )

    count = collect_pending_from_log_tail(prev_log, tmp_path, _settings_enabled())

    assert count == 1
    pending = pending_store.load_all(tmp_path)
    assert pending[0].exception_type == "RuntimeError"


def test_collect_pending_from_log_tail_skips_when_already_reported(tmp_path: Path):
    """If the fingerprint matches a row already in ``reported.txt`` we
    must *not* write a new pending file (spec §9 — don't re-prompt for
    a bug the user already filed).

    Strategy: do a first collection to learn the fingerprint produced
    by this particular ERROR event, mark it reported, wipe the pending
    dir, then collect a second time — count must be 0.
    """
    prev_log = tmp_path / "logs" / "last-session.log.prev"
    _write_log_lines(
        prev_log,
        [
            {
                "level": "ERROR",
                "event_name": "rag.search",
                "exception_type": "RuntimeError",
                "exception_module": "core.retrieval",
            },
        ],
    )
    first = collect_pending_from_log_tail(prev_log, tmp_path, _settings_enabled())
    assert first == 1
    pending = pending_store.load_all(tmp_path)
    assert len(pending) == 1
    fingerprint = pending[0].fingerprint

    # Pretend the user already filed this fingerprint.
    for p in (tmp_path / "crash-pending").glob("*.json"):
        p.unlink()
    reported_store.mark_reported(tmp_path, fingerprint)

    second = collect_pending_from_log_tail(prev_log, tmp_path, _settings_enabled())

    assert second == 0
    assert pending_store.load_all(tmp_path) == []


def test_collect_pending_from_log_tail_returns_zero_without_error_events(
    tmp_path: Path,
):
    """Clean shutdown logs (only INFO / WARNING) yield no pending file."""
    prev_log = tmp_path / "logs" / "last-session.log.prev"
    _write_log_lines(
        prev_log,
        [
            {"level": "INFO", "event_name": "startup"},
            {"level": "WARNING", "event_name": "slow.query", "duration_ms": 4200},
            {"level": "INFO", "event_name": "shutdown"},
        ],
    )

    count = collect_pending_from_log_tail(prev_log, tmp_path, _settings_enabled())

    assert count == 0
    assert pending_store.load_all(tmp_path) == []


def test_collect_pending_from_log_tail_returns_zero_when_prev_log_missing(
    tmp_path: Path,
):
    """No rotated log at all → nothing to ingest (first-ever startup)."""
    prev_log = tmp_path / "logs" / "last-session.log.prev"
    assert not prev_log.exists()

    count = collect_pending_from_log_tail(prev_log, tmp_path, _settings_enabled())

    assert count == 0
    assert pending_store.load_all(tmp_path) == []


def test_collect_pending_from_log_tail_respects_optin_gate(tmp_path: Path):
    """Even with a juicy error event, opt-out (``enabled=False``) and
    not-yet-decided (``enabled=None``) must short-circuit to 0. This is
    the same opt-in gate as ``collector.collect_from_exception``."""
    prev_log = tmp_path / "logs" / "last-session.log.prev"
    _write_log_lines(
        prev_log,
        [
            {
                "level": "ERROR",
                "event_name": "rag.search",
                "exception_type": "RuntimeError",
                "exception_module": "core.retrieval",
            },
        ],
    )

    assert collect_pending_from_log_tail(
        prev_log, tmp_path, CrashReportSettings(enabled=False)
    ) == 0
    assert collect_pending_from_log_tail(
        prev_log, tmp_path, CrashReportSettings(enabled=None)
    ) == 0
    assert pending_store.load_all(tmp_path) == []

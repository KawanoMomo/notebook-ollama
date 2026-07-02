"""Tests for ``core.crash_reporter.pending_store``.

spec §6.1 / plan Task 2.1: 未送信レポート JSON 永続化レイヤ。
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import get_args
from unittest.mock import patch

import pytest

from core.crash_reporter.pending_store import (
    PendingCrash,
    Source,
    delete,
    get,
    load_all,
    save,
)

_VALID_SOURCES: tuple[str, ...] = get_args(Source)


def _make_crash(
    *,
    id_: str = "abc123",
    fingerprint: str = "deadbeef",
    created_at: str = "2026-06-28T00:00:00Z",
    exception_type: str = "RuntimeError",
    exception_message: str = "boom",
    trace: list[str] | None = None,
    hardware: dict | None = None,
    log_tail: list[dict] | None = None,
    source: Source = "fastapi",
) -> PendingCrash:
    return PendingCrash(
        id=id_,
        fingerprint=fingerprint,
        created_at=created_at,
        exception_type=exception_type,
        exception_message=exception_message,
        trace=trace if trace is not None else ["File \"x\", line 1, in <module>"],
        hardware=hardware if hardware is not None else {"cpu_model": "i9"},
        log_tail=log_tail if log_tail is not None else [{"level": "INFO"}],
        source=source,
    )


# ----------------------------------------------------------------------
# save
# ----------------------------------------------------------------------


def test_save_creates_pending_directory_if_missing(tmp_path: Path) -> None:
    crash = _make_crash(id_="x1")
    out = save(tmp_path, crash)
    assert out.exists()
    assert out.parent.name == "crash-pending"
    assert out.parent.parent == tmp_path
    assert out.name == "x1.json"


def test_save_writes_valid_json_with_all_fields(tmp_path: Path) -> None:
    crash = _make_crash(id_="x2")
    out = save(tmp_path, crash)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data == asdict(crash)


def test_save_overwrites_existing_id(tmp_path: Path) -> None:
    save(tmp_path, _make_crash(id_="dup", exception_message="first"))
    save(tmp_path, _make_crash(id_="dup", exception_message="second"))
    crashes = load_all(tmp_path)
    assert len(crashes) == 1
    assert crashes[0].exception_message == "second"


def test_save_returns_path_under_data_dir(tmp_path: Path) -> None:
    out = save(tmp_path, _make_crash(id_="x3"))
    # path is absolute and lives inside data_dir/crash-pending
    assert tmp_path in out.parents


@pytest.mark.parametrize("source", sorted(_VALID_SOURCES))
def test_save_round_trip_for_each_source(tmp_path: Path, source: str) -> None:
    crash = _make_crash(id_=f"src-{source}", source=source)  # type: ignore[arg-type]
    save(tmp_path, crash)
    loaded = get(tmp_path, f"src-{source}")
    assert loaded is not None
    assert loaded.source == source


def test_save_preserves_unicode_cjk(tmp_path: Path) -> None:
    crash = _make_crash(
        id_="cjk1",
        exception_message="クラッシュ発生 😱 — 한국어",
        trace=["ファイル \"テスト.py\"", "行 42"],
    )
    save(tmp_path, crash)
    loaded = get(tmp_path, "cjk1")
    assert loaded is not None
    assert loaded.exception_message == "クラッシュ発生 😱 — 한국어"
    assert loaded.trace[0] == "ファイル \"テスト.py\""


def test_save_is_atomic_no_tmp_file_left_behind(tmp_path: Path) -> None:
    save(tmp_path, _make_crash(id_="atom"))
    pending_dir = tmp_path / "crash-pending"
    tmp_files = list(pending_dir.glob("*.tmp"))
    assert tmp_files == []


def test_save_atomic_replace_when_target_exists(tmp_path: Path) -> None:
    """Interrupted write must not corrupt an existing file.

    If ``os.replace`` is not used (e.g. plain ``open(w)``), an exception mid-write
    would leave a half-written JSON. We simulate this by failing the second save
    AFTER the .tmp is created but BEFORE rename — the original must remain intact.
    """
    save(tmp_path, _make_crash(id_="safe", exception_message="original"))
    pending_dir = tmp_path / "crash-pending"
    target = pending_dir / "safe.json"
    original_bytes = target.read_bytes()

    # Force os.replace to fail to simulate interruption between write and rename.
    with patch("core.crash_reporter.pending_store.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            save(tmp_path, _make_crash(id_="safe", exception_message="corrupted"))

    # Original file is untouched
    assert target.read_bytes() == original_bytes
    # No leftover .tmp files (cleaned up on failure)
    assert list(pending_dir.glob("*.tmp")) == []


# ----------------------------------------------------------------------
# load_all
# ----------------------------------------------------------------------


def test_load_all_returns_empty_when_dir_missing(tmp_path: Path) -> None:
    assert load_all(tmp_path) == []


def test_load_all_returns_empty_when_dir_empty(tmp_path: Path) -> None:
    (tmp_path / "crash-pending").mkdir()
    assert load_all(tmp_path) == []


def test_load_all_orders_by_created_at_descending(tmp_path: Path) -> None:
    save(tmp_path, _make_crash(id_="a", created_at="2026-06-28T00:00:00Z"))
    save(tmp_path, _make_crash(id_="b", created_at="2026-06-29T00:00:00Z"))
    save(tmp_path, _make_crash(id_="c", created_at="2026-06-27T00:00:00Z"))
    out = load_all(tmp_path)
    assert [c.id for c in out] == ["b", "a", "c"]


def test_load_all_skips_corrupted_json(tmp_path: Path) -> None:
    save(tmp_path, _make_crash(id_="good"))
    pending_dir = tmp_path / "crash-pending"
    (pending_dir / "broken.json").write_text("{not valid json", encoding="utf-8")
    out = load_all(tmp_path)
    assert [c.id for c in out] == ["good"]


def test_load_all_skips_files_missing_required_field(tmp_path: Path) -> None:
    save(tmp_path, _make_crash(id_="good"))
    pending_dir = tmp_path / "crash-pending"
    # Valid JSON but missing required fields - should be skipped
    (pending_dir / "incomplete.json").write_text(
        json.dumps({"id": "incomplete", "missing": "fields"}),
        encoding="utf-8",
    )
    out = load_all(tmp_path)
    assert [c.id for c in out] == ["good"]


def test_load_all_skips_empty_file(tmp_path: Path) -> None:
    save(tmp_path, _make_crash(id_="good"))
    pending_dir = tmp_path / "crash-pending"
    (pending_dir / "empty.json").write_text("", encoding="utf-8")
    out = load_all(tmp_path)
    assert [c.id for c in out] == ["good"]


def test_load_all_round_trips_full_dataclass(tmp_path: Path) -> None:
    crash = _make_crash(
        id_="rt",
        hardware={"cpu_model": "i9", "ram_total_gb": 32.0, "gpu_vram_mb": 11264},
        log_tail=[
            {"level": "ERROR", "event_name": "rag.search"},
            {"level": "INFO", "duration_ms": 12},
        ],
    )
    save(tmp_path, crash)
    out = load_all(tmp_path)
    assert len(out) == 1
    assert out[0] == crash


# ----------------------------------------------------------------------
# get
# ----------------------------------------------------------------------


def test_get_returns_none_when_dir_missing(tmp_path: Path) -> None:
    assert get(tmp_path, "anything") is None


def test_get_returns_none_for_unknown_id(tmp_path: Path) -> None:
    save(tmp_path, _make_crash(id_="exists"))
    assert get(tmp_path, "unknown") is None


def test_get_returns_pending_crash_for_known_id(tmp_path: Path) -> None:
    crash = _make_crash(id_="hit")
    save(tmp_path, crash)
    loaded = get(tmp_path, "hit")
    assert loaded == crash


def test_get_returns_none_for_corrupted_file(tmp_path: Path) -> None:
    pending_dir = tmp_path / "crash-pending"
    pending_dir.mkdir()
    (pending_dir / "broken.json").write_text("{garbage", encoding="utf-8")
    assert get(tmp_path, "broken") is None


# ----------------------------------------------------------------------
# delete
# ----------------------------------------------------------------------


def test_delete_returns_true_when_existed(tmp_path: Path) -> None:
    save(tmp_path, _make_crash(id_="del"))
    assert delete(tmp_path, "del") is True
    assert get(tmp_path, "del") is None


def test_delete_returns_false_when_not_existed(tmp_path: Path) -> None:
    assert delete(tmp_path, "ghost") is False


def test_delete_returns_false_when_dir_missing(tmp_path: Path) -> None:
    # data_dir exists but crash-pending does not
    assert delete(tmp_path, "ghost") is False


def test_delete_only_removes_targeted_id(tmp_path: Path) -> None:
    save(tmp_path, _make_crash(id_="keep"))
    save(tmp_path, _make_crash(id_="drop"))
    assert delete(tmp_path, "drop") is True
    remaining = {c.id for c in load_all(tmp_path)}
    assert remaining == {"keep"}


# ----------------------------------------------------------------------
# Source typing
# ----------------------------------------------------------------------


def test_source_literal_includes_spec_listed() -> None:
    must = {
        "fastapi", "excepthook", "signal", "atexit",
        "frontend", "unclean_shutdown",
    }
    assert set(_VALID_SOURCES) == must

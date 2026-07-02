"""Tests for ``core.feedback_hub.notice_store``.

spec §5.3 / plan Sprint 3 Task 3.6: お知らせ JSON 読み込み層。

挙動契約:
- ``data/notices.json`` を読み、``Notice`` のリストを ``date`` 降順で返す。
- ファイル不在 / 壊れた JSON / 想定外スキーマは ``[]`` を返す
  (例外を投げずアプリ起動を妨げない、log.warning で記録)。
- ``id`` / ``date`` / ``title`` / ``body`` のいずれかが欠けた個別エントリは
  skip して残りだけ返す。
- ``subsections`` は任意。あれば ``[{heading, items}]`` の形で保持する。
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

import pytest

from core.feedback_hub.notice_store import Notice, load_notices

# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def _write(path: Path, payload: object) -> Path:
    """Serialize ``payload`` as JSON (UTF-8, no ASCII escape) and return path."""
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _entry(
    *,
    id_: str = "n1",
    date: str = "2026-06-28",
    title: str = "タイトル",
    body: str = "本文です。",
    subsections: list[dict] | None = None,
) -> dict:
    out: dict = {"id": id_, "date": date, "title": title, "body": body}
    if subsections is not None:
        out["subsections"] = subsections
    return out


# ----------------------------------------------------------------------
# round-trip / shape
# ----------------------------------------------------------------------


def test_load_notices_returns_notice_objects(tmp_path: Path) -> None:
    path = _write(tmp_path / "notices.json", {"notices": [_entry()]})
    out = load_notices(path)
    assert len(out) == 1
    assert isinstance(out[0], Notice)
    assert out[0].id == "n1"
    assert out[0].date == "2026-06-28"
    assert out[0].title == "タイトル"
    assert out[0].body == "本文です。"
    assert out[0].subsections is None


def test_load_notices_preserves_subsections(tmp_path: Path) -> None:
    subs = [
        {"heading": "新機能", "items": ["拡声器ハブ", "クラッシュレポート"]},
        {"heading": "改善", "items": ["起動高速化"]},
    ]
    path = _write(tmp_path / "notices.json", {"notices": [_entry(subsections=subs)]})
    out = load_notices(path)
    assert len(out) == 1
    assert out[0].subsections == subs


def test_load_notices_round_trip_via_asdict(tmp_path: Path) -> None:
    """Dataclass → asdict → JSON → load_notices → 同じ値が戻る。"""
    subs = [{"heading": "h", "items": ["i1", "i2"]}]
    entry = _entry(id_="rt", subsections=subs)
    path = _write(tmp_path / "notices.json", {"notices": [entry]})
    out = load_notices(path)
    assert asdict(out[0]) == {
        "id": "rt",
        "date": "2026-06-28",
        "title": "タイトル",
        "body": "本文です。",
        "subsections": subs,
    }


# ----------------------------------------------------------------------
# sorting (ISO date descending)
# ----------------------------------------------------------------------


def test_load_notices_sorted_by_date_descending(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "notices.json",
        {
            "notices": [
                _entry(id_="a", date="2026-06-28"),
                _entry(id_="b", date="2026-06-29"),
                _entry(id_="c", date="2026-06-27"),
            ]
        },
    )
    out = load_notices(path)
    assert [n.id for n in out] == ["b", "a", "c"]


def test_load_notices_sort_across_years_and_months(tmp_path: Path) -> None:
    """ISO 8601 date strings are lexicographically sortable across years/months."""
    path = _write(
        tmp_path / "notices.json",
        {
            "notices": [
                _entry(id_="old", date="2025-12-31"),
                _entry(id_="new", date="2026-01-01"),
                _entry(id_="mid", date="2025-11-15"),
                _entry(id_="future", date="2027-03-04"),
            ]
        },
    )
    out = load_notices(path)
    assert [n.id for n in out] == ["future", "new", "old", "mid"]


# ----------------------------------------------------------------------
# tolerant failure modes (must not throw, must log)
# ----------------------------------------------------------------------


def test_load_notices_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_notices(tmp_path / "does-not-exist.json") == []


def test_load_notices_empty_file_returns_empty(tmp_path: Path) -> None:
    (tmp_path / "empty.json").write_text("", encoding="utf-8")
    assert load_notices(tmp_path / "empty.json") == []


def test_load_notices_malformed_json_returns_empty_and_logs_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    (tmp_path / "bad.json").write_text("{not valid json", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        out = load_notices(tmp_path / "bad.json")
    assert out == []
    # A warning should be logged so operators can spot the bad file.
    assert any(
        record.levelno >= logging.WARNING for record in caplog.records
    ), "expected a warning to be logged for malformed JSON"


def test_load_notices_root_not_dict_returns_empty(tmp_path: Path) -> None:
    path = _write(tmp_path / "list.json", [_entry()])
    assert load_notices(path) == []


def test_load_notices_missing_notices_key_returns_empty(tmp_path: Path) -> None:
    path = _write(tmp_path / "wrong-key.json", {"items": [_entry()]})
    assert load_notices(path) == []


def test_load_notices_notices_not_a_list_returns_empty(tmp_path: Path) -> None:
    path = _write(tmp_path / "wrong-shape.json", {"notices": "oops"})
    assert load_notices(path) == []


# ----------------------------------------------------------------------
# per-entry validation: skip bad entries, keep good ones
# ----------------------------------------------------------------------


@pytest.mark.parametrize("missing_field", ["id", "date", "title", "body"])
def test_load_notices_skips_entry_missing_required_field(
    tmp_path: Path, missing_field: str
) -> None:
    bad = _entry(id_="bad")
    del bad[missing_field]
    good = _entry(id_="good")
    path = _write(tmp_path / "notices.json", {"notices": [bad, good]})
    out = load_notices(path)
    assert [n.id for n in out] == ["good"]


def test_load_notices_skips_non_dict_entry(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "notices.json",
        {"notices": ["just a string", 42, None, _entry(id_="ok")]},
    )
    out = load_notices(path)
    assert [n.id for n in out] == ["ok"]


@pytest.mark.parametrize("field_name", ["id", "date", "title", "body"])
def test_load_notices_skips_entry_with_non_string_required_field(
    tmp_path: Path, field_name: str
) -> None:
    bad = _entry(id_="bad")
    bad[field_name] = 123  # type: ignore[assignment]
    good = _entry(id_="good")
    path = _write(tmp_path / "notices.json", {"notices": [bad, good]})
    out = load_notices(path)
    assert [n.id for n in out] == ["good"]


def test_load_notices_skips_entry_with_malformed_subsections(tmp_path: Path) -> None:
    bad = _entry(id_="bad", subsections=[{"heading": "ok"}])  # missing 'items'
    good = _entry(id_="good", subsections=[{"heading": "ok", "items": ["x"]}])
    path = _write(tmp_path / "notices.json", {"notices": [bad, good]})
    out = load_notices(path)
    assert [n.id for n in out] == ["good"]


def test_load_notices_treats_empty_subsections_list_as_present(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "notices.json",
        {"notices": [_entry(id_="n", subsections=[])]},
    )
    out = load_notices(path)
    assert out[0].subsections == []


# ----------------------------------------------------------------------
# seed file shipped in the repo
# ----------------------------------------------------------------------


def test_repo_seed_notices_file_is_loadable() -> None:
    """The committed ``data/notices.json`` seed must parse cleanly.

    This guards against a typo in the seed silently making the お知らせ tab
    empty in production. We resolve the path relative to repo root.
    """
    repo_root = Path(__file__).resolve().parents[2]
    seed = repo_root / "data" / "notices.json"
    assert seed.is_file(), f"expected seed file at {seed}"
    out = load_notices(seed)
    assert len(out) >= 1, "seed must contain at least one notice"
    # Every loaded entry must have the required string fields populated.
    for n in out:
        assert isinstance(n.id, str) and n.id
        assert isinstance(n.date, str) and n.date
        assert isinstance(n.title, str) and n.title
        assert isinstance(n.body, str) and n.body

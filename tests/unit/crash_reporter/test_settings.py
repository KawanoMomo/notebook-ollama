"""CrashReportSettings model 単体テスト (Sprint 3 Task 3.2)。

spec §7.3 が要求する 3 フィールドの既定値・型 (None / True / None)、および
datetime ISO 8601 ラウンドトリップ (JSON 永続化想定) を検証する。
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from core.crash_reporter.settings import CrashReportSettings


def test_defaults_are_undecided_with_auto_prompt_on():
    """初期値: enabled=None (未決定), auto_prompt=True, opted_in_at=None。

    enabled=None は spec §7.3 で 「初回オプトイン未完了」 のセマンティクスを表す。
    既定で auto_prompt=True なのは、初回クラッシュ時に自動でオプトインダイアログを
    出すための既定挙動 (spec §5 系で参照される)。
    """
    s = CrashReportSettings()
    assert s.enabled is None
    assert s.auto_prompt is True
    assert s.opted_in_at is None


def test_enabled_accepts_true_false_and_none():
    """enabled は bool | None — 3 値ともコンストラクト可能。"""
    assert CrashReportSettings(enabled=True).enabled is True
    assert CrashReportSettings(enabled=False).enabled is False
    assert CrashReportSettings(enabled=None).enabled is None


def test_opted_in_at_accepts_datetime():
    """opted_in_at は datetime オブジェクトを受け取れる。"""
    when = datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC)
    s = CrashReportSettings(opted_in_at=when)
    assert s.opted_in_at == when


def test_opted_in_at_parses_iso8601_string():
    """settings.json から読み込んだ ISO 文字列を datetime に解釈する (ラウンドトリップ)。"""
    s = CrashReportSettings(opted_in_at="2026-06-28T12:00:00+00:00")
    assert isinstance(s.opted_in_at, datetime)
    assert s.opted_in_at.year == 2026
    assert s.opted_in_at.month == 6
    assert s.opted_in_at.day == 28
    assert s.opted_in_at.hour == 12


def test_json_dump_serializes_datetime_to_iso_string():
    """model_dump(mode='json') で datetime → ISO 8601 string になり、
    settings.json への書き込み (json.dumps) でも例外なくシリアライズできる。"""
    when = datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC)
    s = CrashReportSettings(enabled=True, auto_prompt=False, opted_in_at=when)
    payload = s.model_dump(mode="json")
    assert payload["enabled"] is True
    assert payload["auto_prompt"] is False
    assert isinstance(payload["opted_in_at"], str)
    # json.dumps を通せること = 永続化可能
    text = json.dumps(payload)
    decoded = json.loads(text)
    # 再構築でラウンドトリップ
    s2 = CrashReportSettings(**decoded)
    assert s2.enabled is True
    assert s2.auto_prompt is False
    assert s2.opted_in_at == when


def test_round_trip_with_none_datetime():
    """opted_in_at=None でもラウンドトリップ可能 (初期状態の永続化)。"""
    s = CrashReportSettings()
    payload = s.model_dump(mode="json")
    text = json.dumps(payload)
    decoded = json.loads(text)
    s2 = CrashReportSettings(**decoded)
    assert s2.enabled is None
    assert s2.auto_prompt is True
    assert s2.opted_in_at is None


def test_round_trip_with_enabled_false():
    """enabled=False (明示的オプトアウト) もラウンドトリップで保持される。
    None と False は意味が違う (未決定 vs 拒否) ので、両方を識別できること。"""
    s = CrashReportSettings(enabled=False)
    payload = s.model_dump(mode="json")
    s2 = CrashReportSettings(**payload)
    assert s2.enabled is False  # not None


def test_rejects_invalid_enabled_type():
    """enabled に bool / None として解釈不能な値を渡したら ValidationError。

    pydantic は "yes" / 1 のような曖昧値を bool に強制変換するため、
    確実に bool に解釈できない構造体 (dict) を投げて型バリデーションが
    効いていることを確認する。
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CrashReportSettings(enabled={"x": 1})  # type: ignore[arg-type]


def test_rejects_invalid_opted_in_at_string():
    """opted_in_at に ISO で解釈不能な文字列を渡したら ValidationError。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CrashReportSettings(opted_in_at="not-a-date")  # type: ignore[arg-type]

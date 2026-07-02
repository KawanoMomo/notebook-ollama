"""CrashReportSettings の `core/config.py` / `core/settings_store.py` 結線テスト
(Sprint 3 Task 3.2)。

`audio` / `ollama` セクションと同じ保存/復元パターンに乗せて、

- 既定値 (`enabled=None`, `auto_prompt=True`, `opted_in_at=None`) が、
  `settings.json` に該当キーが無いとき AppConfig 既定として現れること。
- 既存環境 (= `settings.json` が `audio` / `ollama` だけで `crash_report` を
  持たない) でも apply_overrides が落ちないこと (バックワード互換)。
- 保存→ロードで datetime が ISO 文字列としてラウンドトリップすること。
- 部分更新 (`opted_in_at` だけ書き換え) で他フィールド (`auto_prompt`) が
  維持されること。
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from core.config import AppConfig
from core.crash_reporter.settings import CrashReportSettings
from core.settings_store import (
    apply_overrides,
    load_crash_report,
    save_crash_report,
)


def test_app_config_default_crash_report_is_undecided(memory_data_dir):
    """settings.json が存在しないとき、AppConfig.crash_report は既定値。"""
    cfg = AppConfig(data_dir=memory_data_dir)
    assert cfg.crash_report.enabled is None
    assert cfg.crash_report.auto_prompt is True
    assert cfg.crash_report.opted_in_at is None


def test_apply_overrides_no_crash_section_keeps_defaults(memory_data_dir):
    """既存ユーザの settings.json には crash_report キーが無い。
    その場合でも apply_overrides は例外を出さず、既定値で続行する
    (バックワード互換: 旧クライアントの settings.json 由来)。"""
    (memory_data_dir / "settings.json").write_text(
        json.dumps({"audio": {"keep_audio": False}}),
        encoding="utf-8",
    )
    cfg = AppConfig(data_dir=memory_data_dir)
    apply_overrides(cfg)
    assert cfg.crash_report.enabled is None
    assert cfg.crash_report.auto_prompt is True
    assert cfg.crash_report.opted_in_at is None
    # 同時に audio override が壊れていないことも確認 (既存挙動を回帰で守る)。
    assert cfg.audio.keep_audio is False


def test_apply_overrides_restores_crash_report(memory_data_dir):
    """settings.json の crash_report セクションが in-memory cfg に反映される。"""
    (memory_data_dir / "settings.json").write_text(
        json.dumps(
            {
                "crash_report": {
                    "enabled": True,
                    "auto_prompt": False,
                    "opted_in_at": "2026-06-28T12:00:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )
    cfg = AppConfig(data_dir=memory_data_dir)
    apply_overrides(cfg)
    assert cfg.crash_report.enabled is True
    assert cfg.crash_report.auto_prompt is False
    assert isinstance(cfg.crash_report.opted_in_at, datetime)
    assert cfg.crash_report.opted_in_at == datetime(
        2026, 6, 28, 12, 0, 0, tzinfo=UTC
    )


def test_invalid_crash_report_override_does_not_crash_startup(memory_data_dir):
    """型不正な crash_report オーバーライドで apply_overrides がクラッシュしない。
    (audio / ollama と同じ防御契約: 既定で続行)。"""
    (memory_data_dir / "settings.json").write_text(
        json.dumps({"crash_report": {"enabled": "not-a-bool"}}),
        encoding="utf-8",
    )
    cfg = AppConfig(data_dir=memory_data_dir)
    apply_overrides(cfg)  # 例外を投げないこと
    # 既定にフォールバック
    assert cfg.crash_report.enabled is None
    assert cfg.crash_report.auto_prompt is True


def test_save_and_load_crash_report_round_trip(memory_data_dir):
    """save_crash_report -> load_crash_report で全フィールドがラウンドトリップする。
    datetime は ISO 8601 文字列として settings.json に書き出されるが、
    load 側で datetime オブジェクトに復元される。"""
    when = datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC)
    save_crash_report(
        memory_data_dir,
        CrashReportSettings(enabled=True, auto_prompt=False, opted_in_at=when),
    )

    # settings.json に文字列で書かれていること (永続化フォーマット)
    raw = json.loads((memory_data_dir / "settings.json").read_text(encoding="utf-8"))
    assert raw["crash_report"]["enabled"] is True
    assert raw["crash_report"]["auto_prompt"] is False
    assert isinstance(raw["crash_report"]["opted_in_at"], str)
    assert raw["crash_report"]["opted_in_at"].startswith("2026-06-28T12:00:00")

    loaded = load_crash_report(memory_data_dir)
    assert loaded.enabled is True
    assert loaded.auto_prompt is False
    assert loaded.opted_in_at == when


def test_load_crash_report_when_missing_returns_defaults(memory_data_dir):
    """settings.json が無い / crash_report キーが無いとき、load は既定値を返す。"""
    loaded = load_crash_report(memory_data_dir)
    assert loaded.enabled is None
    assert loaded.auto_prompt is True
    assert loaded.opted_in_at is None


def test_save_crash_report_preserves_other_sections(memory_data_dir):
    """crash_report 保存が既存の audio / ollama セクションを壊さないこと
    (save_section ベースなので audio / ollama と同じ "セクション merge" 契約)。"""
    (memory_data_dir / "settings.json").write_text(
        json.dumps({"audio": {"keep_audio": False}, "ollama": {"default_model": "x"}}),
        encoding="utf-8",
    )
    save_crash_report(memory_data_dir, CrashReportSettings(enabled=True))
    raw = json.loads((memory_data_dir / "settings.json").read_text(encoding="utf-8"))
    assert raw["audio"]["keep_audio"] is False
    assert raw["ollama"]["default_model"] == "x"
    assert raw["crash_report"]["enabled"] is True


def test_partial_update_opted_in_at_preserves_auto_prompt(memory_data_dir):
    """opted_in_at だけ書き換えても他フィールドが維持される。

    ユースケース: 初回オプトイン時に enabled=True / opted_in_at=now を保存する場面で、
    auto_prompt は明示的に変えていないなら以前の値 (True) を保持したい。
    load → 部分更新 → save の典型パターン。
    """
    # 初期: enabled=True, auto_prompt=False を永続化
    save_crash_report(
        memory_data_dir,
        CrashReportSettings(enabled=True, auto_prompt=False, opted_in_at=None),
    )
    # 後段: opted_in_at だけ更新したい — 既存値を load してから merge
    existing = load_crash_report(memory_data_dir)
    when = datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC)
    updated = existing.model_copy(update={"opted_in_at": when})
    save_crash_report(memory_data_dir, updated)

    after = load_crash_report(memory_data_dir)
    assert after.opted_in_at == when
    assert after.auto_prompt is False  # 維持されていること
    assert after.enabled is True  # こちらも維持

from __future__ import annotations

import json
from pathlib import Path

from core.crash_reporter.settings import CrashReportSettings
from core.logging import get_logger

log = get_logger("settings_store")

_FILE = "settings.json"
_CRASH_REPORT_SECTION = "crash_report"


def settings_path(data_dir: Path) -> Path:
    return data_dir / _FILE


def load_overrides(data_dir: Path) -> dict:
    """settings.json を読む。無い/壊れている場合は空 dict。"""
    p = settings_path(data_dir)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_section(data_dir: Path, section: str, values: dict) -> None:
    """settings.json の 1 セクション(例 "audio")を更新して書き戻す。"""
    data = load_overrides(data_dir)
    data[section] = values
    p = settings_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_overrides(config) -> None:
    """起動時: 永続化された audio オーバーライドを config.audio へ適用。
    永続値 > config 既定(env 含む)。手編集や旧スキーマで settings.json に
    型不正な値が入っていても起動を止めないよう、適用失敗時は既定値のまま続行する。"""
    ov = load_overrides(config.data_dir)
    audio = ov.get("audio")
    if isinstance(audio, dict) and audio:
        merged = {**config.audio.model_dump(), **audio}
        try:
            config.audio = config.audio.__class__(**merged)
        except Exception:
            # 不正な settings.json で起動をクラッシュさせない (既定値で続行)。
            log.warning("settings_override_invalid", section="audio")

    ollama = ov.get("ollama")
    if isinstance(ollama, dict) and ollama:
        # 永続化された ollama セクションを一体で適用する: default_model に加え
        # embedding_model / embedding_dim も復元する。これにより、埋め込み切替後の
        # 再起動で embedding_model が config 既定(bge-m3/1024)へ巻き戻り、
        # 768 次元の collection に 1024 次元ベクトルを投げて全検索・全取込が
        # 壊れる事故を構造的に防ぐ(model と次元は一体・順序非依存)。
        # audio 方式と同じく丸ごとマージし、不正値でも起動を止めない。
        merged = {**config.ollama.model_dump(), **ollama}
        try:
            config.ollama = config.ollama.__class__(**merged)
        except Exception:
            # 不正な settings.json で起動をクラッシュさせない (既定値で続行)。
            log.warning("settings_override_invalid", section="ollama")

    dev = ov.get("dev")
    if isinstance(dev, dict) and dev:
        # 開発者モード設定を復元する(容量はクランプ)。不正値でも起動を止めない。
        from core.dev_logs.ring import clamp_capacity
        merged = {**config.dev.model_dump(), **dev}
        try:
            merged["log_capacity_bytes"] = clamp_capacity(
                int(merged.get("log_capacity_bytes", config.dev.log_capacity_bytes))
            )
            config.dev = config.dev.__class__(**merged)
        except Exception:
            log.warning("settings_override_invalid", section="dev")

    generation = ov.get("generation")
    if isinstance(generation, dict) and generation:
        # 生成設定 (response_budget_tokens / context_budget_ratio) を復元する。
        # audio / ollama と同じ規約: 丸ごとマージし、不正値でも起動を止めない。
        merged = {**config.generation.model_dump(), **generation}
        try:
            config.generation = config.generation.__class__(**merged)
        except Exception:
            log.warning("settings_override_invalid", section="generation")

    crash_report = ov.get(_CRASH_REPORT_SECTION)
    if isinstance(crash_report, dict) and crash_report:
        # crash_report セクションを既定値にマージ適用する (audio / ollama と同じ規約)。
        # 既存ユーザの settings.json には crash_report キーが存在しないため、
        # キー欠落時は何もせず既定値 (enabled=None, auto_prompt=True) のままにする
        # = バックワード互換。型不正 (例: enabled="yes") でも起動を止めない。
        merged = {**config.crash_report.model_dump(mode="json"), **crash_report}
        try:
            config.crash_report = CrashReportSettings(**merged)
        except Exception:
            log.warning("settings_override_invalid", section=_CRASH_REPORT_SECTION)


def load_crash_report(data_dir: Path) -> CrashReportSettings:
    """settings.json から crash_report セクションだけを取り出して
    CrashReportSettings を返す。キー欠落・破損ファイルでは既定値を返す。

    AppConfig 経由ではなく単発で読み書きしたい呼び出し側
    (オプトインフロー UI / collector) のためのショートカット。
    """
    ov = load_overrides(data_dir)
    raw = ov.get(_CRASH_REPORT_SECTION)
    if not isinstance(raw, dict):
        return CrashReportSettings()
    try:
        return CrashReportSettings(**raw)
    except Exception:
        # 型不正値での起動クラッシュを避ける契約は apply_overrides と同じ。
        log.warning("settings_override_invalid", section=_CRASH_REPORT_SECTION)
        return CrashReportSettings()


def save_crash_report(data_dir: Path, settings: CrashReportSettings) -> None:
    """CrashReportSettings を settings.json の crash_report セクションへ保存する。

    datetime フィールド (opted_in_at) は ``model_dump(mode='json')`` で ISO 8601
    文字列に変換してから書き出すので、json.dumps が ``TypeError`` を起こすことなく
    永続化できる。``save_section`` が他セクション (audio / ollama) をマージ保持する
    のと同じ規約。
    """
    payload = settings.model_dump(mode="json")
    save_section(data_dir, _CRASH_REPORT_SECTION, payload)

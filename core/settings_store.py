from __future__ import annotations

import json
from pathlib import Path

from core.logging import get_logger

log = get_logger("settings_store")

_FILE = "settings.json"


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

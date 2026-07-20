"""voice_input 設定の GET/PUT roundtrip と永続化(spec §5 設定フィールド)。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.config import AppConfig


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_get_settings_includes_voice_input_defaults(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    assert r.json()["voice_input"] == {"mode": "push_to_talk", "ptt_key": "Space"}


def test_put_voice_input_roundtrip(client):
    r = client.put(
        "/api/settings/voice-input",
        json={"mode": "hands_free", "ptt_key": "KeyV"},
    )
    assert r.status_code == 200
    assert r.json() == {"mode": "hands_free", "ptt_key": "KeyV"}

    r = client.get("/api/settings")
    assert r.json()["voice_input"] == {"mode": "hands_free", "ptt_key": "KeyV"}


def test_put_voice_input_rejects_unknown_mode(client):
    r = client.put(
        "/api/settings/voice-input",
        json={"mode": "always_on", "ptt_key": "Space"},
    )
    assert r.status_code == 422


def test_put_voice_input_rejects_empty_key(client):
    r = client.put(
        "/api/settings/voice-input",
        json={"mode": "push_to_talk", "ptt_key": ""},
    )
    assert r.status_code == 422


def test_voice_input_persisted_to_settings_json(client, tmp_path):
    client.put(
        "/api/settings/voice-input",
        json={"mode": "off", "ptt_key": "F9"},
    )
    data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert data["voice_input"] == {"mode": "off", "ptt_key": "F9"}


def test_apply_overrides_restores_voice_input(tmp_path):
    """再起動シミュレーション: settings.json の voice_input が AppConfig へ復元される。"""
    from core.settings_store import apply_overrides, save_section

    save_section(tmp_path, "voice_input", {"mode": "off", "ptt_key": "F9"})
    cfg = AppConfig(data_dir=tmp_path)
    apply_overrides(cfg)
    assert cfg.voice_input.mode == "off"
    assert cfg.voice_input.ptt_key == "F9"

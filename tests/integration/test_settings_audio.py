from __future__ import annotations

import json

from fastapi.testclient import TestClient

from apps.api.main import create_app


def test_get_settings_includes_audio(memory_data_dir):
    with TestClient(create_app()) as client:
        r = client.get("/api/settings")
        assert r.status_code == 200
        audio = r.json()["audio"]
        assert audio["storage_format"] == "aac"
        assert audio["keep_audio"] is True


def test_put_audio_roundtrip_and_persist(memory_data_dir):
    with TestClient(create_app()) as client:
        audio = client.get("/api/settings").json()["audio"]
        audio["storage_format"] = "opus"
        audio["keep_audio"] = False
        audio["storage_bitrate_kbps"] = 48
        r = client.put("/api/settings/audio", json=audio)
        assert r.status_code == 200
        assert r.json()["storage_format"] == "opus"
        # 同一プロセス内 GET で反映
        again = client.get("/api/settings").json()["audio"]
        assert again["storage_format"] == "opus"
        assert again["keep_audio"] is False
        assert again["storage_bitrate_kbps"] == 48

    # 永続化ファイルが書かれている
    sj = memory_data_dir / "settings.json"
    assert sj.exists()
    assert json.loads(sj.read_text(encoding="utf-8"))["audio"]["storage_format"] == "opus"

    # 再起動(新 app・同 data_dir)で反映
    with TestClient(create_app()) as client2:
        reloaded = client2.get("/api/settings").json()["audio"]
        assert reloaded["storage_format"] == "opus"
        assert reloaded["keep_audio"] is False


def test_put_audio_rejects_invalid_format(memory_data_dir):
    with TestClient(create_app()) as client:
        audio = client.get("/api/settings").json()["audio"]
        audio["storage_format"] = "flac"  # 非対応
        r = client.put("/api/settings/audio", json=audio)
        assert r.status_code == 422


def test_invalid_audio_override_does_not_crash_startup(memory_data_dir):
    """型不正な settings.json で起動をクラッシュさせず、既定値で続行する。"""
    (memory_data_dir / "settings.json").write_text(
        '{"audio": {"name_threshold": "not-a-number"}}', encoding="utf-8"
    )
    with TestClient(create_app()) as client:
        r = client.get("/api/settings")
        assert r.status_code == 200
        assert r.json()["audio"]["name_threshold"] == 0.65

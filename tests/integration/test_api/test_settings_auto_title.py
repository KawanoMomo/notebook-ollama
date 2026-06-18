"""GET /api/settings の audio に auto_title(既定 True)が載り、
PUT /api/settings/audio で round-trip することを検証する統合テスト。"""

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_get_settings_exposes_auto_title_default_true(client):
    r = client.get("/api/settings")
    assert r.status_code == 200, r.text
    audio = r.json()["audio"]
    assert audio["auto_title"] is True


def test_put_audio_settings_round_trips_auto_title(client):
    audio = client.get("/api/settings").json()["audio"]
    audio["auto_title"] = False
    r = client.put("/api/settings/audio", json=audio)
    assert r.status_code == 200, r.text
    assert r.json()["auto_title"] is False
    # 永続化 + in-memory 反映: 再取得でも False。
    assert client.get("/api/settings").json()["audio"]["auto_title"] is False

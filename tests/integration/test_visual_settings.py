from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import create_app


def _enable_beta(client) -> None:
    client.put("/api/features/table-figure-rag", json={"enabled": True})


def test_put_visual_403_when_beta_off(memory_data_dir):
    with TestClient(create_app()) as client:
        res = client.put("/api/settings/visual", json={"search_enabled": False})
        assert res.status_code == 403


def test_visual_settings_roundtrip_and_persist(memory_data_dir):
    with TestClient(create_app()) as client:
        _enable_beta(client)
        assert client.get("/api/settings").json()["visual"]["search_enabled"] is True
        res = client.put("/api/settings/visual", json={"search_enabled": False})
        assert res.status_code == 200 and res.json()["search_enabled"] is False
        assert client.get("/api/settings").json()["visual"]["search_enabled"] is False
    # 再起動(新app・同data_dir)後も永続
    with TestClient(create_app()) as client2:
        assert client2.get("/api/settings").json()["visual"]["search_enabled"] is False

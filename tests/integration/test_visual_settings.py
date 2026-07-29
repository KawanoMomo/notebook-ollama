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


def test_get_settings_exposes_index_unit_and_strategy(memory_data_dir):
    with TestClient(create_app()) as client:
        res = client.get("/api/settings")
        assert res.status_code == 200
        visual = res.json()["visual"]
        # 既定は現行挙動と一致する
        assert visual["index_unit"] == "page"
        assert visual["search_strategy"] == "hybrid_rrf"


def test_put_visual_updates_index_unit_only(memory_data_dir):
    with TestClient(create_app()) as client:
        _enable_beta(client)
        res = client.put("/api/settings/visual", json={"index_unit": "tile"})
        assert res.status_code == 200
        body = res.json()
        assert body["index_unit"] == "tile"
        # 触っていないフィールドは変わらない
        assert body["search_enabled"] is True
        assert body["search_strategy"] == "hybrid_rrf"


def test_put_visual_updates_strategy_and_persists(memory_data_dir):
    with TestClient(create_app()) as client:
        _enable_beta(client)
        res = client.put("/api/settings/visual", json={"search_strategy": "pixel_native"})
        assert res.status_code == 200
        assert res.json()["search_strategy"] == "pixel_native"
        # 永続化されている(GET で読み直せる)
        assert client.get("/api/settings").json()["visual"]["search_strategy"] == "pixel_native"


def test_put_visual_rejects_unknown_unit(memory_data_dir):
    with TestClient(create_app()) as client:
        _enable_beta(client)
        res = client.put("/api/settings/visual", json={"index_unit": "region"})
        assert res.status_code == 422


def test_put_visual_search_enabled_alone_still_works(memory_data_dir):
    """既存FEは {search_enabled} だけを送る。後方互換を壊さないこと。"""
    with TestClient(create_app()) as client:
        _enable_beta(client)
        res = client.put("/api/settings/visual", json={"search_enabled": False})
        assert res.status_code == 200
        assert res.json()["search_enabled"] is False
        assert res.json()["index_unit"] == "page"

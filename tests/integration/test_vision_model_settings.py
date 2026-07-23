from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import create_app


def test_put_vision_model_rejects_non_vision_model(memory_data_dir, monkeypatch):
    import apps.api.routers.settings as settings_mod

    class FakeClient:
        async def list_tags(self):
            return [{"name": "qwen2.5:14b"}]

        async def show(self, model):
            return {"capabilities": ["completion", "chat"]}

    monkeypatch.setattr(settings_mod, "OllamaClient", lambda **kw: FakeClient())
    with TestClient(create_app()) as client:
        res = client.put("/api/settings/vision-model", json={"model": "qwen2.5:14b"})
        assert res.status_code == 400


def test_put_vision_model_accepts_vision_model(memory_data_dir, monkeypatch):
    import apps.api.routers.settings as settings_mod

    class FakeClient:
        async def list_tags(self):
            return [{"name": "qwen3-vl"}]

        async def show(self, model):
            return {"capabilities": ["completion", "vision"]}

    monkeypatch.setattr(settings_mod, "OllamaClient", lambda **kw: FakeClient())
    with TestClient(create_app()) as client:
        res = client.put("/api/settings/vision-model", json={"model": "qwen3-vl"})
        assert res.status_code == 200
        assert res.json()["vision_model"] == "qwen3-vl"

        # 同一プロセス内 GET で反映
        res2 = client.get("/api/settings")
        assert res2.json()["ollama"]["vision_model"] == "qwen3-vl"

    # 再起動(新 app・同 data_dir)後も永続化されている
    with TestClient(create_app()) as client2:
        again = client2.get("/api/settings").json()
        assert again["ollama"]["vision_model"] == "qwen3-vl"


def test_put_vision_model_empty_string_clears_selection(memory_data_dir, monkeypatch):
    import apps.api.routers.settings as settings_mod

    class FakeClient:
        async def list_tags(self):
            return [{"name": "qwen3-vl"}]

        async def show(self, model):
            return {"capabilities": ["completion", "vision"]}

    monkeypatch.setattr(settings_mod, "OllamaClient", lambda **kw: FakeClient())
    with TestClient(create_app()) as client:
        client.put("/api/settings/vision-model", json={"model": "qwen3-vl"})
        res = client.put("/api/settings/vision-model", json={"model": ""})
        assert res.status_code == 200
        assert res.json()["vision_model"] == ""

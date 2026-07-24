from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import create_app


def _enable_beta(client) -> None:
    client.put("/api/features/table-figure-rag", json={"enabled": True})


def test_put_vision_model_403_when_beta_off(memory_data_dir):
    """回帰テスト: spec の「OFF時: 視覚モデル(VLM)スロットは非露出(APIは403+
    有効化ヒント)」に対し、put_vision_model が require_feature ガードなしで
    ベータOFFでも 200 を返していた(evaluator scenario 8で発覚)。"""
    with TestClient(create_app()) as client:
        res = client.put("/api/settings/vision-model", json={"model": "qwen3-vl"})
        assert res.status_code == 403


def test_put_vision_model_rejects_non_vision_model(memory_data_dir, monkeypatch):
    import apps.api.routers.settings as settings_mod

    class FakeClient:
        async def list_tags(self):
            return [{"name": "qwen2.5:14b"}]

        async def show(self, model):
            return {"capabilities": ["completion", "chat"]}

    monkeypatch.setattr(settings_mod, "OllamaClient", lambda **kw: FakeClient())
    with TestClient(create_app()) as client:
        _enable_beta(client)
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
        _enable_beta(client)
        res = client.put("/api/settings/vision-model", json={"model": "qwen3-vl"})
        assert res.status_code == 200
        assert res.json()["vision_model"] == "qwen3-vl"

        # 同一プロセス内 GET で反映
        res2 = client.get("/api/settings")
        assert res2.json()["ollama"]["vision_model"] == "qwen3-vl"

    # 再起動(新 app・同 data_dir)後も永続化されている(ベータ opt-in も同様に永続化)
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
        _enable_beta(client)
        client.put("/api/settings/vision-model", json={"model": "qwen3-vl"})
        res = client.put("/api/settings/vision-model", json={"model": ""})
        assert res.status_code == 200
        assert res.json()["vision_model"] == ""


def test_vision_model_survives_default_model_change_and_restart(memory_data_dir, monkeypatch):
    """回帰テスト: PUT /settings/ollama(既定チャットモデル変更)が settings.json の
    ollama セクションを再構築しても、既に設定済みの vision_model を消さないこと。
    put_ollama_settings は default_model/embedding_model/embedding_dim の3キーだけで
    セクションを save_section していたため、vision_model フィールド追加後は
    その次に default_model を変えるだけで再起動時に消える経路があった。"""
    import apps.api.routers.settings as settings_mod

    class FakeClient:
        async def list_tags(self):
            return [{"name": "qwen3-vl"}, {"name": "qwen2.5:14b"}]

        async def show(self, model):
            if model == "qwen3-vl":
                return {"capabilities": ["completion", "vision"]}
            return {"capabilities": ["completion", "chat"]}

    monkeypatch.setattr(settings_mod, "OllamaClient", lambda **kw: FakeClient())
    with TestClient(create_app()) as client:
        _enable_beta(client)
        res = client.put("/api/settings/vision-model", json={"model": "qwen3-vl"})
        assert res.json()["vision_model"] == "qwen3-vl"

        res = client.put("/api/settings/ollama", json={"default_model": "qwen2.5:14b"})
        assert res.status_code == 200

    with TestClient(create_app()) as client2:
        again = client2.get("/api/settings").json()
        assert again["ollama"]["default_model"] == "qwen2.5:14b"
        assert again["ollama"]["vision_model"] == "qwen3-vl"

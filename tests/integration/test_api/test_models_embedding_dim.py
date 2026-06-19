import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        yield c


class _FakeOllamaClient:
    """list_models が使う raw client を差し替えるためのスタブ。"""

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def list_tags(self):
        return [
            {"name": "qwen2.5:14b", "size": 100, "details": {"family": "qwen"}},
            {"name": "bge-m3", "size": 50, "details": {"family": "bert"}},
        ]

    async def show(self, model):
        if model == "bge-m3":
            return {"capabilities": ["embedding"], "parameters": ""}
        return {"capabilities": ["completion"], "parameters": "num_ctx 8192"}


def test_models_embedding_dim_for_embedding_models(client, monkeypatch):
    # list_models が new する raw client を fake に差し替え
    monkeypatch.setattr("apps.api.routers.models.OllamaClient", _FakeOllamaClient)

    # gateway.embed を fake 化(埋め込みモデルだけ 1024 を返す)
    async def fake_embed(*, model, text):
        assert model == "bge-m3"
        return [0.0] * 1024

    client.app.state.ctx.ollama.embed = fake_embed  # type: ignore[method-assign]

    resp = client.get("/api/models")
    assert resp.status_code == 200
    by_name = {m["name"]: m for m in resp.json()["models"]}
    # 埋め込みモデルには probe 由来の dim が付く
    assert by_name["bge-m3"]["embedding_dim"] == 1024
    # チャットモデルは null
    assert by_name["qwen2.5:14b"]["embedding_dim"] is None

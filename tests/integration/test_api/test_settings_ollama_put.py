from __future__ import annotations

import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    app = create_app()
    with TestClient(app) as c:
        yield c


def _mock_tags_and_show(router, *, name: str, capabilities: list[str]) -> None:
    router.get("http://fake/api/tags").mock(
        return_value=httpx.Response(
            200,
            json={"models": [{"name": name, "size": 1}]},
        )
    )
    router.post("http://fake/api/show").mock(
        return_value=httpx.Response(200, json={"capabilities": capabilities})
    )


def test_ollama_settings_update_schema_accepts_default_model():
    from apps.api.schemas.settings import OllamaSettingsUpdate

    body = OllamaSettingsUpdate(default_model="qwen2.5:14b")
    assert body.default_model == "qwen2.5:14b"


def test_put_ollama_accepts_chat_model_and_persists(client, tmp_path):
    with respx.mock(assert_all_called=False) as router:
        _mock_tags_and_show(router, name="qwen2.5:14b", capabilities=["completion"])
        r = client.put("/api/settings/ollama", json={"default_model": "qwen2.5:14b"})
    assert r.status_code == 200
    assert r.json()["default_model"] == "qwen2.5:14b"

    # 同一プロセス内 GET で反映
    again = client.get("/api/settings").json()["ollama"]
    assert again["default_model"] == "qwen2.5:14b"

    # 永続化ファイル
    sj = tmp_path / "settings.json"
    assert sj.exists()
    saved = json.loads(sj.read_text(encoding="utf-8"))["ollama"]
    assert saved["default_model"] == "qwen2.5:14b"
    # ollama セクションはマージ更新。既存 ollama 永続値が無い初回は
    # in-memory cfg(既定)から embedding_model/embedding_dim を補完する。
    assert saved["embedding_model"] == "bge-m3"
    assert saved["embedding_dim"] == 1024


def test_put_ollama_rejects_embedding_only_model(client):
    with respx.mock(assert_all_called=False) as router:
        _mock_tags_and_show(router, name="bge-m3", capabilities=["embedding"])
        r = client.put("/api/settings/ollama", json={"default_model": "bge-m3"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "input.invalid"


def test_put_ollama_rejects_unknown_model(client):
    with respx.mock(assert_all_called=False) as router:
        # tags には別モデルしか無い → 指定モデルは未存在
        router.get("http://fake/api/tags").mock(
            return_value=httpx.Response(
                200, json={"models": [{"name": "qwen2.5:14b", "size": 1}]}
            )
        )
        r = client.put("/api/settings/ollama", json={"default_model": "does-not-exist"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "input.invalid"


def test_put_ollama_persists_across_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    with TestClient(create_app()) as c1:
        with respx.mock(assert_all_called=False) as router:
            _mock_tags_and_show(router, name="qwen2.5:14b", capabilities=["completion"])
            r = c1.put("/api/settings/ollama", json={"default_model": "qwen2.5:14b"})
        assert r.status_code == 200

    # 新 app(同 data_dir)起動 → apply_overrides で反映
    with TestClient(create_app()) as c2:
        ollama = c2.get("/api/settings").json()["ollama"]
        assert ollama["default_model"] == "qwen2.5:14b"


def test_put_ollama_preserves_existing_embedding_dim(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    # 先に非既定の埋め込みを永続化(再インデックス済み状態を模す)
    (tmp_path / "settings.json").write_text(
        json.dumps(
            {
                "ollama": {
                    "default_model": "qwen2.5:14b",
                    "embedding_model": "nomic-embed-text",
                    "embedding_dim": 768,
                }
            }
        ),
        encoding="utf-8",
    )
    with TestClient(create_app()) as c:
        with respx.mock(assert_all_called=False) as router:
            _mock_tags_and_show(
                router, name="llama3.1:8b", capabilities=["completion"]
            )
            r = c.put("/api/settings/ollama", json={"default_model": "llama3.1:8b"})
        assert r.status_code == 200

    saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["ollama"]
    # LLM 既定は更新される
    assert saved["default_model"] == "llama3.1:8b"
    # 埋め込みは巻き戻らず温存される(1024 に戻らない)
    assert saved["embedding_model"] == "nomic-embed-text"
    assert saved["embedding_dim"] == 768

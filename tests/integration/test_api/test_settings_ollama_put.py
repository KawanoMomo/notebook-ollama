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

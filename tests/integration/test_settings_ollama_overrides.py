from __future__ import annotations

import json

from fastapi.testclient import TestClient

from apps.api.main import create_app


def test_apply_overrides_applies_ollama_default_model(memory_data_dir):
    (memory_data_dir / "settings.json").write_text(
        json.dumps(
            {
                "ollama": {
                    "default_model": "llama3.1:8b",
                    "embedding_model": "bge-m3",
                    "embedding_dim": 1024,
                }
            }
        ),
        encoding="utf-8",
    )
    with TestClient(create_app()) as client:
        ollama = client.get("/api/settings").json()["ollama"]
        assert ollama["default_model"] == "llama3.1:8b"
        # embedding_model は保持される(本タスクでは default_model のみ反映対象)。
        assert ollama["embedding_model"] == "bge-m3"


def test_invalid_ollama_override_does_not_crash_startup(memory_data_dir):
    """型不正な ollama オーバーライドで起動をクラッシュさせず既定で続行する。"""
    (memory_data_dir / "settings.json").write_text(
        '{"ollama": {"default_model": 12345}}', encoding="utf-8"
    )
    with TestClient(create_app()) as client:
        r = client.get("/api/settings")
        assert r.status_code == 200
        # 既定モデルに戻る(core/config.py OllamaSettings.default_model)。
        assert r.json()["ollama"]["default_model"] == "qwen2.5:14b"

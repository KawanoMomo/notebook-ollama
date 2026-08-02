"""Integration tests for Sprint 3 / Task 3.3 — acceleration backend fields
flow through settings.json + AppSettingsSchema without breaking existing
settings.json files."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from apps.api.main import create_app
from apps.api.schemas.settings import AudioSettingsSchema, OllamaSettingsSchema
from core.config import AppConfig
from core.settings_store import apply_overrides

# ---------------------------------------------------------------------------
# Backward-compat: settings.json from before Sprint 3 must still load.
# ---------------------------------------------------------------------------

def test_existing_settings_json_without_new_fields_still_loads(memory_data_dir):
    """Pre-Sprint-3 settings.json (no transcriber_backend / runtime_backend
    keys) must load without crash and surface "auto" defaults."""
    (memory_data_dir / "settings.json").write_text(
        json.dumps(
            {
                "audio": {
                    "storage_format": "opus",
                    "keep_audio": False,
                    "storage_bitrate_kbps": 48,
                },
                "ollama": {
                    "default_model": "llama3.1:8b",
                    "embedding_model": "bge-m3",
                    "embedding_dim": 1024,
                },
            }
        ),
        encoding="utf-8",
    )

    # apply_overrides path (lifespan): no crash, defaults present.
    config = AppConfig(data_dir=memory_data_dir)
    apply_overrides(config)
    assert config.audio.transcriber_backend == "auto"
    assert config.audio.diarizer_backend == "auto"
    assert config.audio.speaker_embed_backend == "auto"
    assert config.ollama.runtime_backend == "auto"
    assert config.ollama.text_embed_backend == "auto"
    # And the pre-Sprint-3 fields the user actually had set are preserved.
    assert config.audio.storage_format == "opus"
    assert config.audio.keep_audio is False
    assert config.ollama.default_model == "llama3.1:8b"

    # API surface (lifespan -> /api/settings) returns "auto" for the new keys.
    with TestClient(create_app()) as client:
        body = client.get("/api/settings").json()
        assert body["audio"]["transcriber_backend"] == "auto"
        assert body["audio"]["diarizer_backend"] == "auto"
        assert body["audio"]["speaker_embed_backend"] == "auto"
        assert body["ollama"]["runtime_backend"] == "auto"
        assert body["ollama"]["text_embed_backend"] == "auto"


# ---------------------------------------------------------------------------
# Round-trip: explicit values written to settings.json reload identically.
# ---------------------------------------------------------------------------

def test_settings_round_trip_explicit_backend_values(memory_data_dir):
    """Write settings.json with explicit Phase-1 backend ids; reload via
    apply_overrides; values match."""
    (memory_data_dir / "settings.json").write_text(
        json.dumps(
            {
                "audio": {
                    "transcriber_backend": "faster-whisper-cpu",
                    "diarizer_backend": "sherpa-onnx-cpu",
                    "speaker_embed_backend": "sherpa-onnx-cpu",
                },
                "ollama": {
                    "default_model": "qwen2.5:14b",
                    "embedding_model": "bge-m3",
                    "embedding_dim": 1024,
                    "runtime_backend": "ollama-cuda",
                    "text_embed_backend": "ollama-bge-m3-cpu",
                },
            }
        ),
        encoding="utf-8",
    )

    config = AppConfig(data_dir=memory_data_dir)
    apply_overrides(config)
    assert config.audio.transcriber_backend == "faster-whisper-cpu"
    assert config.audio.diarizer_backend == "sherpa-onnx-cpu"
    assert config.audio.speaker_embed_backend == "sherpa-onnx-cpu"
    assert config.ollama.runtime_backend == "ollama-cuda"
    assert config.ollama.text_embed_backend == "ollama-bge-m3-cpu"


def test_settings_round_trip_openai_compat_values(memory_data_dir):
    """Phase 1.5 (addendum 2026-08-02): openai-compat backend + endpoints
    persist through settings.json -> apply_overrides."""
    (memory_data_dir / "settings.json").write_text(
        json.dumps(
            {
                "ollama": {
                    "default_model": "qwen2.5:14b",
                    "embedding_model": "bge-m3",
                    "embedding_dim": 1024,
                    "runtime_backend": "openai-compat",
                    "text_embed_backend": "openai-compat-embed",
                    "openai_compat_endpoint": "http://localhost:8080",
                    "openai_compat_embed_endpoint": "http://localhost:9090",
                },
            }
        ),
        encoding="utf-8",
    )

    config = AppConfig(data_dir=memory_data_dir)
    apply_overrides(config)
    assert config.ollama.runtime_backend == "openai-compat"
    assert config.ollama.text_embed_backend == "openai-compat-embed"
    assert config.ollama.openai_compat_endpoint == "http://localhost:8080"
    assert config.ollama.openai_compat_embed_endpoint == "http://localhost:9090"


def test_get_api_exposes_openai_compat_endpoints(memory_data_dir):
    """GET /api/settings surfaces the new diagnostic fields (api_key は返さない)。

    runtime_backend=openai-compat まで立てて lifespan(build_context)が
    OpenAICompatClient gateway を実際に構築できることも同時に検証する。"""
    (memory_data_dir / "settings.json").write_text(
        json.dumps(
            {
                "ollama": {
                    "default_model": "qwen2.5:14b",
                    "embedding_model": "bge-m3",
                    "embedding_dim": 1024,
                    "runtime_backend": "openai-compat",
                    "openai_compat_endpoint": "http://localhost:8080",
                    "openai_compat_api_key": "sk-secret",
                },
            }
        ),
        encoding="utf-8",
    )
    with TestClient(create_app()) as client:
        body = client.get("/api/settings").json()
        assert body["ollama"]["runtime_backend"] == "openai-compat"
        assert body["ollama"]["openai_compat_endpoint"] == "http://localhost:8080"
        assert body["ollama"]["openai_compat_embed_endpoint"] == ""
        # 秘匿値は GET 応答に含めない
        assert "sk-secret" not in json.dumps(body)


def test_settings_round_trip_via_get_api_reflects_persisted_backend_values(
    memory_data_dir,
):
    """End-to-end: persisted file -> lifespan apply_overrides -> /api/settings
    JSON body carries the explicit backend ids."""
    (memory_data_dir / "settings.json").write_text(
        json.dumps(
            {
                "audio": {
                    "transcriber_backend": "faster-whisper-cpu",
                },
                "ollama": {
                    "default_model": "qwen2.5:14b",
                    "embedding_model": "bge-m3",
                    "embedding_dim": 1024,
                    "runtime_backend": "ollama-cuda",
                },
            }
        ),
        encoding="utf-8",
    )
    with TestClient(create_app()) as client:
        body = client.get("/api/settings").json()
        assert body["audio"]["transcriber_backend"] == "faster-whisper-cpu"
        # other audio backend fields still default
        assert body["audio"]["diarizer_backend"] == "auto"
        assert body["audio"]["speaker_embed_backend"] == "auto"
        assert body["ollama"]["runtime_backend"] == "ollama-cuda"
        assert body["ollama"]["text_embed_backend"] == "auto"


# ---------------------------------------------------------------------------
# Schema-level validation: invalid values must raise ValidationError, both at
# the pydantic schema layer (PUT body) and at the AppConfig layer.
# ---------------------------------------------------------------------------

def _minimal_audio_payload() -> dict:
    return {
        "whisper_model": "large-v3",
        "device": "cuda",
        "compute_type": "float16",
        "live_caption_default": True,
        "agc_enabled": True,
        "diarization_enabled": True,
        "voiceprint_naming": True,
        "name_inference_llm": True,
        "name_threshold": 0.65,
        "storage_format": "aac",
        "storage_bitrate_kbps": 64,
        "keep_audio": True,
        "auto_title": True,
    }


def test_audio_schema_rejects_invalid_transcriber_backend():
    payload = _minimal_audio_payload() | {"transcriber_backend": "bogus"}
    with pytest.raises(ValidationError):
        AudioSettingsSchema(**payload)


def test_audio_schema_rejects_phase_2_only_id():
    """Phase 2 ids leak guard at the API schema layer."""
    payload = _minimal_audio_payload() | {"transcriber_backend": "openvino-whisper-igpu"}
    with pytest.raises(ValidationError):
        AudioSettingsSchema(**payload)


def test_ollama_schema_rejects_invalid_runtime_backend():
    with pytest.raises(ValidationError):
        OllamaSettingsSchema(
            endpoint="http://localhost:11434",
            default_model="qwen2.5:14b",
            embedding_model="bge-m3",
            runtime_backend="ipex-llm-ollama",  # Phase 2 only
        )


def test_app_config_apply_overrides_drops_bogus_backend_value(memory_data_dir):
    """Defense-in-depth: settings_store.apply_overrides catches ValidationError
    from a hand-edited settings.json and falls back to defaults rather than
    crashing the app (matches existing behavior for other invalid fields)."""
    (memory_data_dir / "settings.json").write_text(
        json.dumps(
            {"audio": {"transcriber_backend": "bogus-backend-id"}},
        ),
        encoding="utf-8",
    )
    config = AppConfig(data_dir=memory_data_dir)
    apply_overrides(config)
    # Falls back to defaults — does not crash, does not propagate "bogus".
    assert config.audio.transcriber_backend == "auto"


# ---------------------------------------------------------------------------
# PUT /api/settings/audio round-trip: editing via the API persists and
# re-loads the new backend fields (Phase 1 UI keeps these read-only, but the
# schema must support write so future Phase 2 widening + tests can drive it).
# ---------------------------------------------------------------------------

def test_put_audio_round_trips_backend_fields(memory_data_dir):
    with TestClient(create_app()) as client:
        audio = client.get("/api/settings").json()["audio"]
        assert audio["transcriber_backend"] == "auto"
        audio["transcriber_backend"] = "faster-whisper-cpu"
        r = client.put("/api/settings/audio", json=audio)
        assert r.status_code == 200, r.text
        assert r.json()["transcriber_backend"] == "faster-whisper-cpu"

    # New process / same data_dir: persisted value survives restart.
    with TestClient(create_app()) as client2:
        again = client2.get("/api/settings").json()["audio"]
        assert again["transcriber_backend"] == "faster-whisper-cpu"

"""Unit tests for Sprint 3 / Task 3.3 — AppConfig acceleration backend fields.

These cover the in-memory defaults / validation. Persistence round-trip is
covered by tests/integration/test_settings_acceleration_fields.py.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.config import AppConfig, AudioSettings, OllamaSettings


def test_audio_backend_fields_default_auto():
    audio = AudioSettings()
    assert audio.transcriber_backend == "auto"
    assert audio.diarizer_backend == "auto"
    assert audio.speaker_embed_backend == "auto"


def test_ollama_backend_fields_default_auto():
    ollama = OllamaSettings()
    assert ollama.runtime_backend == "auto"
    assert ollama.text_embed_backend == "auto"


def test_app_config_exposes_backend_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    cfg = AppConfig()
    assert cfg.audio.transcriber_backend == "auto"
    assert cfg.audio.diarizer_backend == "auto"
    assert cfg.audio.speaker_embed_backend == "auto"
    assert cfg.ollama.runtime_backend == "auto"
    assert cfg.ollama.text_embed_backend == "auto"


def test_phase_1_allowed_audio_backend_values():
    """Phase 1 Literal: only auto + faster-whisper-{cuda,cpu} / sherpa-onnx-cpu."""
    AudioSettings(transcriber_backend="auto")
    AudioSettings(transcriber_backend="faster-whisper-cuda")
    AudioSettings(transcriber_backend="faster-whisper-cpu")
    AudioSettings(diarizer_backend="sherpa-onnx-cpu")
    AudioSettings(speaker_embed_backend="sherpa-onnx-cpu")


def test_phase_1_allowed_ollama_backend_values():
    OllamaSettings(runtime_backend="auto")
    OllamaSettings(runtime_backend="ollama-cuda")
    OllamaSettings(text_embed_backend="auto")
    OllamaSettings(text_embed_backend="ollama-bge-m3-cpu")


def test_new_field_validation_rejects_bogus_transcriber_backend():
    with pytest.raises(ValidationError):
        AudioSettings(transcriber_backend="bogus")


def test_new_field_validation_rejects_phase_2_only_ids_for_phase_1_literal():
    """Phase 2 ids must NOT be accepted by the Phase 1 Literal — otherwise the
    BackendFactory silent-fail guard never triggers."""
    with pytest.raises(ValidationError):
        AudioSettings(transcriber_backend="openvino-whisper-igpu")
    with pytest.raises(ValidationError):
        OllamaSettings(runtime_backend="ipex-llm-ollama")
    with pytest.raises(ValidationError):
        OllamaSettings(text_embed_backend="openvino-bge-m3-npu")


def test_existing_audio_settings_kwargs_still_construct_with_backend_defaults():
    """Backward-compat: callers (tests, settings_store) that pass only the
    pre-Sprint-3 audio fields must still construct cleanly, with new fields
    defaulting to "auto" — proves the additions are non-breaking."""
    audio = AudioSettings(whisper_model="large-v3", device="cuda")
    assert audio.transcriber_backend == "auto"
    assert audio.diarizer_backend == "auto"
    assert audio.speaker_embed_backend == "auto"
    ollama = OllamaSettings(endpoint="http://localhost:11434")
    assert ollama.runtime_backend == "auto"
    assert ollama.text_embed_backend == "auto"

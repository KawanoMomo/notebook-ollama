"""Sprint 2 / Task 2.1 — BACKEND_IDS constants (Phase 1.5 rework).

Validates the per-role frozenset structure of ``BACKEND_IDS`` *and* that the
permanently-dropped backend ids (user decisions captured in
``docs/superpowers/plans/2026-06-29-igpu-npu-acceleration.md`` and the spec
addendum "Update 2026-08-02") have not silently re-entered the table:

* ``amd-whispercpp-npu`` — dropped from STT (pywhispercpp continuity risk +
  model quality validation cost).
* ``amd-whispercpp-dml`` — renamed to ``amd-whispercpp-vulkan`` (whisper.cpp
  has no DirectML backend; DirectML is maintenance-mode — addendum N).
* ``sherpa-onnx-dml`` / ``sherpa-onnx-openvino-gpu`` /
  ``sherpa-onnx-openvino-npu`` — dropped from DIARIZE. Diarizer and speaker
  embedder are CPU-only on every host in v1+v2.
* ``ipex-llm-ollama`` — dropped from LLM (upstream archived + known security
  issues — addendum K2).
* ``ollama-directml`` — dropped from LLM (Ollama never shipped a DirectML
  backend; the official iGPU path is Vulkan — addendum K1).
"""

from __future__ import annotations

import pytest

from core.accel.backend_ids import BACKEND_IDS


def test_backend_ids_excludes_amd_whispercpp_npu() -> None:
    """User decision: amd-whispercpp-npu is permanently dropped from v1."""
    assert "amd-whispercpp-npu" not in BACKEND_IDS["STT"]


def test_backend_ids_excludes_amd_whispercpp_dml() -> None:
    """Addendum 2026-08-02: whisper.cpp has no DirectML backend — the AMD
    STT id rides Vulkan."""
    assert "amd-whispercpp-dml" not in BACKEND_IDS["STT"]
    assert "amd-whispercpp-vulkan" in BACKEND_IDS["STT"]


@pytest.mark.parametrize(
    "forbidden_id",
    [
        "sherpa-onnx-dml",
        "sherpa-onnx-openvino-gpu",
        "sherpa-onnx-openvino-npu",
    ],
)
def test_backend_ids_excludes_sherpa_onnx_gpu_npu_variants(forbidden_id: str) -> None:
    """User decision: sherpa-onnx GPU/NPU variants are dropped in v1."""
    assert forbidden_id not in BACKEND_IDS["DIARIZE"]


@pytest.mark.parametrize(
    "forbidden_id",
    [
        # Addendum K2: archived upstream + "known security issues" README.
        "ipex-llm-ollama",
        # Addendum K1: Ollama has no DirectML backend (Vulkan is official).
        "ollama-directml",
    ],
)
def test_backend_ids_excludes_dropped_llm_ids(forbidden_id: str) -> None:
    assert forbidden_id not in BACKEND_IDS["LLM"]


def test_backend_ids_diarize_is_cpu_only() -> None:
    """Diarizer is the single sherpa-onnx-cpu choice on every host."""
    assert BACKEND_IDS["DIARIZE"] == frozenset({"sherpa-onnx-cpu"})


def test_backend_ids_stt_set_matches_contract() -> None:
    """STT set matches the Phase 1.5 contract (Phase 2 builders declared but
    not yet implemented)."""
    expected = frozenset(
        {
            "faster-whisper-cuda",
            "faster-whisper-cpu",
            "openvino-whisper-igpu",
            "openvino-whisper-npu",
            "amd-whispercpp-vulkan",
        }
    )
    assert BACKEND_IDS["STT"] == expected


def test_backend_ids_llm_set_matches_contract() -> None:
    """LLM set per addendum K1/K2/L: vulkan promoted, ipex/directml dropped,
    openai-compat added as the second common contract."""
    expected = frozenset({"ollama-cuda", "ollama-vulkan", "openai-compat"})
    assert BACKEND_IDS["LLM"] == expected


def test_backend_ids_text_embed_set_matches_contract() -> None:
    expected = frozenset(
        {
            "ollama-bge-m3-cpu",
            "openai-compat-embed",
            "openvino-bge-m3-igpu",
            "openvino-bge-m3-npu",
        }
    )
    assert BACKEND_IDS["TEXT_EMBED"] == expected


@pytest.mark.parametrize("role", ["STT", "DIARIZE", "LLM", "TEXT_EMBED"])
def test_backend_ids_values_are_frozensets(role: str) -> None:
    """Each role value must be a frozenset (hashable, immutable)."""
    assert isinstance(BACKEND_IDS[role], frozenset)


def test_backend_ids_top_level_roles() -> None:
    """Top-level keys are exactly the 4 v1 roles."""
    assert set(BACKEND_IDS.keys()) == {"STT", "DIARIZE", "LLM", "TEXT_EMBED"}

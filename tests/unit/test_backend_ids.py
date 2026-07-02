"""Sprint 2 / Task 2.1 — BACKEND_IDS constants.

Validates the per-role frozenset structure of ``BACKEND_IDS`` *and* that the
permanently-dropped backend ids (user decisions captured in
``docs/superpowers/plans/2026-06-29-igpu-npu-acceleration.md``) have not
silently re-entered the table:

* ``amd-whispercpp-npu`` — dropped from STT (pywhispercpp continuity risk +
  model quality validation cost). AMD ryzen ai users go through the DirectML
  LLM path only.
* ``sherpa-onnx-dml`` / ``sherpa-onnx-openvino-gpu`` /
  ``sherpa-onnx-openvino-npu`` — dropped from DIARIZE. Diarizer and speaker
  embedder are CPU-only on every host in v1+v2.
"""

from __future__ import annotations

import pytest

from core.accel.backend_ids import BACKEND_IDS


def test_backend_ids_excludes_amd_whispercpp_npu() -> None:
    """User decision: amd-whispercpp-npu is permanently dropped from v1."""
    assert "amd-whispercpp-npu" not in BACKEND_IDS["STT"]


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


def test_backend_ids_diarize_is_cpu_only() -> None:
    """Diarizer is the single sherpa-onnx-cpu choice on every host."""
    assert BACKEND_IDS["DIARIZE"] == frozenset({"sherpa-onnx-cpu"})


def test_backend_ids_stt_set_matches_v1_contract() -> None:
    """STT set matches the Phase 1 contract (Phase 2 builders declared but
    not yet implemented)."""
    expected = frozenset(
        {
            "faster-whisper-cuda",
            "faster-whisper-cpu",
            "openvino-whisper-igpu",
            "openvino-whisper-npu",
            "amd-whispercpp-dml",
        }
    )
    assert BACKEND_IDS["STT"] == expected


def test_backend_ids_llm_set_matches_v1_contract() -> None:
    expected = frozenset({"ollama-cuda", "ollama-directml", "ipex-llm-ollama"})
    assert BACKEND_IDS["LLM"] == expected


def test_backend_ids_text_embed_set_matches_v1_contract() -> None:
    expected = frozenset(
        {
            "ollama-bge-m3-cpu",
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

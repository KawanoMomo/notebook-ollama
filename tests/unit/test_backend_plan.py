"""Sprint 2 / Task 2.1 — ``BackendPlan`` dataclass + ``is_phase1_implementable``.

* ``BackendPlan`` must be a frozen dataclass (FrozenInstanceError on field
  assignment).
* Constructor validation rejects ids that are not in the matching
  ``BACKEND_IDS`` role frozenset (typo guard + dropped-id guard).
* ``is_phase1_implementable`` returns True iff every id in the plan is one
  the Phase 1 BackendFactory can build (CUDA + CPU only).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

import pytest

from core.accel.plan import BackendPlan, is_phase1_implementable
from core.accel.profile import _STUB_PROFILE, HwProfile

_CUDA_PROFILE: HwProfile = HwProfile(
    vendor="nvidia",
    cpu_brand="12th Gen Intel(R) Core(TM) i9-12900KF",
    dgpu="NVIDIA CUDA dGPU",
    igpu=None,
    npu=None,
    vram_mb=11264,
    ryzen_ai_gen=None,
    openvino_devices=(),
    has_directml=False,
    has_cuda=True,
    cuda_device_count=1,
)


def _valid_cuda_plan() -> BackendPlan:
    """All ids inside the Phase 1 implementable subset."""
    return BackendPlan(
        stt_id="faster-whisper-cuda",
        diarize_id="sherpa-onnx-cpu",
        llm_id="ollama-cuda",
        text_embed_id="ollama-bge-m3-cpu",
        hw_profile=_CUDA_PROFILE,
        reason="RTX 2080 Ti detected -> faster-whisper-cuda",
    )


def _openvino_plan() -> BackendPlan:
    """Valid plan whose stt_id is declared but not yet Phase 1 implementable."""
    return BackendPlan(
        stt_id="openvino-whisper-igpu",
        diarize_id="sherpa-onnx-cpu",
        llm_id="ipex-llm-ollama",
        text_embed_id="openvino-bge-m3-igpu",
        hw_profile=_STUB_PROFILE,
        reason="Intel iGPU detected -> openvino-whisper-igpu (Phase 2)",
    )


def test_backend_plan_is_frozen() -> None:
    """Frozen dataclass: field assignment must raise FrozenInstanceError."""
    plan = _valid_cuda_plan()
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.stt_id = "faster-whisper-cpu"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("plan_factory", "expected"),
    [
        (_valid_cuda_plan, True),
        (_openvino_plan, False),
    ],
)
def test_is_phase1_implementable(
    plan_factory: Callable[[], BackendPlan], expected: bool
) -> None:
    """Cuda+cpu plan is implementable; openvino plan is not."""
    assert is_phase1_implementable(plan_factory()) is expected


def test_invalid_stt_id_in_plan_raises() -> None:
    """Constructing BackendPlan with stt_id='bogus' raises ValueError."""
    with pytest.raises(ValueError, match="unknown backend id"):
        BackendPlan(
            stt_id="bogus",
            diarize_id="sherpa-onnx-cpu",
            llm_id="ollama-cuda",
            text_embed_id="ollama-bge-m3-cpu",
            hw_profile=_CUDA_PROFILE,
            reason="bogus stt id",
        )


def test_invalid_diarize_id_in_plan_raises() -> None:
    """Dropped sherpa-onnx-dml is rejected by constructor validation."""
    with pytest.raises(ValueError, match="unknown backend id"):
        BackendPlan(
            stt_id="faster-whisper-cuda",
            diarize_id="sherpa-onnx-dml",
            llm_id="ollama-cuda",
            text_embed_id="ollama-bge-m3-cpu",
            hw_profile=_CUDA_PROFILE,
            reason="dropped diarize id",
        )


def test_invalid_llm_id_in_plan_raises() -> None:
    with pytest.raises(ValueError, match="unknown backend id"):
        BackendPlan(
            stt_id="faster-whisper-cuda",
            diarize_id="sherpa-onnx-cpu",
            llm_id="bogus-llm",
            text_embed_id="ollama-bge-m3-cpu",
            hw_profile=_CUDA_PROFILE,
            reason="bogus llm id",
        )


def test_invalid_text_embed_id_in_plan_raises() -> None:
    with pytest.raises(ValueError, match="unknown backend id"):
        BackendPlan(
            stt_id="faster-whisper-cuda",
            diarize_id="sherpa-onnx-cpu",
            llm_id="ollama-cuda",
            text_embed_id="bogus-embed",
            hw_profile=_CUDA_PROFILE,
            reason="bogus text embed id",
        )


def test_amd_whispercpp_npu_rejected_by_plan_constructor() -> None:
    """Dropped id cannot sneak in through BackendPlan even if BACKEND_IDS
    were ever mistakenly mutated."""
    with pytest.raises(ValueError, match="unknown backend id"):
        BackendPlan(
            stt_id="amd-whispercpp-npu",
            diarize_id="sherpa-onnx-cpu",
            llm_id="ollama-cuda",
            text_embed_id="ollama-bge-m3-cpu",
            hw_profile=_CUDA_PROFILE,
            reason="dropped amd npu id",
        )


def test_valid_plan_preserves_fields() -> None:
    plan = _valid_cuda_plan()
    assert plan.stt_id == "faster-whisper-cuda"
    assert plan.diarize_id == "sherpa-onnx-cpu"
    assert plan.llm_id == "ollama-cuda"
    assert plan.text_embed_id == "ollama-bge-m3-cpu"
    assert plan.hw_profile is _CUDA_PROFILE
    assert "faster-whisper-cuda" in plan.reason

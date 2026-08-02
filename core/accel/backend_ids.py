"""``BACKEND_IDS`` — canonical id sets the Planner is allowed to route to.

Sprint 2 / Task 2.1 of `docs/superpowers/plans/2026-06-29-igpu-npu-acceleration.md`,
reworked by the spec addendum "Update 2026-08-02" (Phase 1.5).

Per-role frozensets:

* ``STT`` — speech-to-text transcribers.
* ``DIARIZE`` — speaker diarization. v1 CPU-only (single id).
* ``LLM`` — chat / summarization runtime.
* ``TEXT_EMBED`` — text embedding model server for RAG.

User decisions reflected here (and asserted at module-import time so a
careless re-introduction can't slip in unnoticed):

* ``amd-whispercpp-npu`` is **dropped** from ``STT`` (pywhispercpp continuity
  risk + model quality validation cost).
* sherpa-onnx GPU/NPU variants (``sherpa-onnx-dml`` /
  ``sherpa-onnx-openvino-gpu`` / ``sherpa-onnx-openvino-npu``) are **dropped**
  from ``DIARIZE``. Diarizer and speaker embedder are CPU-only on every host
  in v1+v2.

Addendum 2026-08-02 (K1/K2/L) decisions:

* ``ipex-llm-ollama`` is **dropped** from ``LLM`` — upstream intel/ipex-llm
  is archived with "known security issues" in its README (addendum K2).
* ``ollama-directml`` is **dropped** from ``LLM`` — Ollama never shipped a
  DirectML backend; the official iGPU path is Vulkan, enabled by default
  since v0.13 (addendum K1). Replaced by ``ollama-vulkan``.
* ``amd-whispercpp-dml`` is **renamed** to ``amd-whispercpp-vulkan`` —
  whisper.cpp has no DirectML backend either (its GPU backends are CUDA /
  Vulkan / CoreML / OpenVINO), and DirectML itself is in maintenance mode
  (addendum N). The AMD STT path, when Phase 2 ships it, rides Vulkan.
* ``openai-compat`` / ``openai-compat-embed`` are **added** — a second
  common contract next to the Ollama HTTP API (addendum L). Never picked
  automatically; reachable only through an explicit user override, pointing
  at any OpenAI-compatible server (llama-server / OVMS / Lemonade /
  LM Studio / Foundry Local).

Phase 1 vs Phase 2:

* The Planner is free to pick any id in ``BACKEND_IDS`` — it is pure data,
  driven by ``HwProfile`` alone.
* ``core.accel.factory.BackendFactory`` only knows how to build the
  currently-implementable subset (see
  ``core.accel.plan.PHASE1_IMPLEMENTABLE_IDS``). Picking an id outside that
  subset is a "Planner picked something Phase 2 hasn't shipped" signal —
  surfaced by ``core.accel.plan.is_phase1_implementable``. The separation is
  intentional: Planner is pure data, Factory is the gate.
"""

from __future__ import annotations

from typing import Final

BACKEND_IDS: Final[dict[str, frozenset[str]]] = {
    "STT": frozenset(
        {
            "faster-whisper-cuda",
            "faster-whisper-cpu",
            "openvino-whisper-igpu",
            "openvino-whisper-npu",
            "amd-whispercpp-vulkan",
        }
    ),
    "DIARIZE": frozenset(
        {
            "sherpa-onnx-cpu",
        }
    ),
    "LLM": frozenset(
        {
            "ollama-cuda",
            "ollama-vulkan",
            "openai-compat",
        }
    ),
    "TEXT_EMBED": frozenset(
        {
            "ollama-bge-m3-cpu",
            "openai-compat-embed",
            "openvino-bge-m3-igpu",
            "openvino-bge-m3-npu",
        }
    ),
}

# Sentinel guards — verified at module-import time so that a careless
# re-introduction of any dropped id can't slip in unnoticed.
_DROPPED_STT_IDS: Final[frozenset[str]] = frozenset(
    {
        "amd-whispercpp-npu",
        # Addendum 2026-08-02: whisper.cpp has no DirectML backend; the AMD
        # STT id rides Vulkan (``amd-whispercpp-vulkan``) instead.
        "amd-whispercpp-dml",
    }
)
_DROPPED_DIARIZE_IDS: Final[frozenset[str]] = frozenset(
    {
        "sherpa-onnx-dml",
        "sherpa-onnx-openvino-gpu",
        "sherpa-onnx-openvino-npu",
    }
)
_DROPPED_LLM_IDS: Final[frozenset[str]] = frozenset(
    {
        # Addendum K2: intel/ipex-llm is archived + flagged with known
        # security issues. Do not re-adopt.
        "ipex-llm-ollama",
        # Addendum K1: Ollama has no DirectML backend; superseded by
        # ``ollama-vulkan`` (official, default-enabled since v0.13).
        "ollama-directml",
    }
)


def _validate_no_dropped_ids() -> None:
    """Fail loudly at import time if a dropped id reappears."""
    leaked_stt = BACKEND_IDS["STT"] & _DROPPED_STT_IDS
    if leaked_stt:
        raise RuntimeError(
            f"BACKEND_IDS['STT'] contains dropped ids: {sorted(leaked_stt)}. "
            "These were removed by user decision and must not be re-added."
        )
    leaked_diarize = BACKEND_IDS["DIARIZE"] & _DROPPED_DIARIZE_IDS
    if leaked_diarize:
        raise RuntimeError(
            f"BACKEND_IDS['DIARIZE'] contains dropped ids: {sorted(leaked_diarize)}. "
            "Diarizer is cpu-only in v1; GPU/NPU variants were removed."
        )
    leaked_llm = BACKEND_IDS["LLM"] & _DROPPED_LLM_IDS
    if leaked_llm:
        raise RuntimeError(
            f"BACKEND_IDS['LLM'] contains dropped ids: {sorted(leaked_llm)}. "
            "ipex-llm-ollama (security issues) and ollama-directml (no such "
            "Ollama backend) were removed by the 2026-08-02 addendum."
        )


_validate_no_dropped_ids()


__all__ = ["BACKEND_IDS"]

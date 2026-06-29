"""``BACKEND_IDS`` — canonical id sets the Planner is allowed to route to.

Sprint 2 / Task 2.1 of `docs/superpowers/plans/2026-06-29-igpu-npu-acceleration.md`.

Per-role frozensets:

* ``STT`` — speech-to-text transcribers.
* ``DIARIZE`` — speaker diarization. v1 CPU-only (single id).
* ``LLM`` — chat / summarization runtime.
* ``TEXT_EMBED`` — text embedding model server for RAG.

User decisions reflected here (and asserted at module-import time so a
careless re-introduction can't slip in unnoticed):

* ``amd-whispercpp-npu`` is **dropped** from ``STT`` (pywhispercpp continuity
  risk + model quality validation cost). AMD users go through the DirectML
  LLM path only.
* sherpa-onnx GPU/NPU variants (``sherpa-onnx-dml`` /
  ``sherpa-onnx-openvino-gpu`` / ``sherpa-onnx-openvino-npu``) are **dropped**
  from ``DIARIZE``. Diarizer and speaker embedder are CPU-only on every host
  in v1+v2.

Phase 1 vs Phase 2:

* The Planner is free to pick any id in ``BACKEND_IDS`` — it is pure data,
  driven by ``HwProfile`` alone.
* ``core.accel.factory.BackendFactory`` only knows how to build the Phase 1
  subset (see ``core.accel.plan.PHASE1_IMPLEMENTABLE_IDS``). Picking an id
  outside that subset is a "Planner picked something Phase 2 hasn't shipped"
  signal — surfaced by ``core.accel.plan.is_phase1_implementable``. The
  separation is intentional: Planner is pure data, Factory is the gate.
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
            "amd-whispercpp-dml",
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
            "ollama-directml",
            "ipex-llm-ollama",
        }
    ),
    "TEXT_EMBED": frozenset(
        {
            "ollama-bge-m3-cpu",
            "openvino-bge-m3-igpu",
            "openvino-bge-m3-npu",
        }
    ),
}

# Sentinel guards — verified at module-import time so that a careless
# re-introduction of any dropped id can't slip in unnoticed.
_DROPPED_STT_IDS: Final[frozenset[str]] = frozenset({"amd-whispercpp-npu"})
_DROPPED_DIARIZE_IDS: Final[frozenset[str]] = frozenset(
    {
        "sherpa-onnx-dml",
        "sherpa-onnx-openvino-gpu",
        "sherpa-onnx-openvino-npu",
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


_validate_no_dropped_ids()


__all__ = ["BACKEND_IDS"]

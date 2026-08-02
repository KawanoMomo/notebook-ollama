"""``BackendPlan`` frozen dataclass + Phase 1 implementability gate.

Sprint 2 / Task 2.1 of `docs/superpowers/plans/2026-06-29-igpu-npu-acceleration.md`.

``BackendPlan`` is the Planner's output — a 4-id tuple bundled with the
``HwProfile`` that produced it and a human-readable ``reason`` so log /
diagnostic surfaces can explain "why was this backend picked?" without
re-deriving the decision tree.

``is_phase1_implementable`` is the gate between "Planner picked an id" and
"Factory can build it". Phase 1 only ships CUDA + CPU builders; if the
Planner routes to (e.g.) ``openvino-whisper-igpu`` on an Intel host the
plan is *valid* (id is in ``BACKEND_IDS``) but *not yet implementable*. The
Acceleration tab / startup log uses this to decide whether to fall back to
a CPU plan or surface a "Phase 2 backend not yet available" diagnostic.

Validation: the constructor's ``__post_init__`` rejects ids that are not in
the matching ``BACKEND_IDS`` role frozenset (typo guard + dropped-id guard).
This is the second line of defence behind the module-import sentinel in
``core.accel.backend_ids``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from core.accel.backend_ids import BACKEND_IDS
from core.accel.profile import HwProfile

# Subset of ``BACKEND_IDS`` that ``core.accel.factory.BackendFactory`` can
# build today. Everything else is "Planner picked something Phase 2
# hasn't shipped" — surfaced via ``is_phase1_implementable``.
#
# Phase 1.5 (addendum 2026-08-02) additions:
#
# * ``ollama-vulkan`` — same builder as ``ollama-cuda``: the Vulkan backend
#   lives inside the official Ollama server process, so from this app's side
#   it is just the configured Ollama endpoint. Buildable everywhere.
# * ``openai-compat`` / ``openai-compat-embed`` — an ``OllamaGateway``
#   wrapping ``OpenAICompatClient`` at ``ollama.openai_compat_endpoint``.
#   Buildable once the endpoint is configured (empty endpoint raises a
#   clear ``ValueError`` at build time).
PHASE1_IMPLEMENTABLE_IDS: Final[dict[str, frozenset[str]]] = {
    "STT": frozenset({"faster-whisper-cuda", "faster-whisper-cpu"}),
    "DIARIZE": frozenset({"sherpa-onnx-cpu"}),
    "LLM": frozenset({"ollama-cuda", "ollama-vulkan", "openai-compat"}),
    "TEXT_EMBED": frozenset({"ollama-bge-m3-cpu", "openai-compat-embed"}),
}


@dataclass(frozen=True)
class BackendPlan:
    """Planner's resolved backend selection for a given ``HwProfile``.

    Fields:
        stt_id: One of ``BACKEND_IDS["STT"]``. The speech-to-text backend
            id the Planner chose.
        diarize_id: One of ``BACKEND_IDS["DIARIZE"]`` — always
            ``"sherpa-onnx-cpu"`` in v1 (diarizer is CPU-only on every host).
        llm_id: One of ``BACKEND_IDS["LLM"]``.
        text_embed_id: One of ``BACKEND_IDS["TEXT_EMBED"]``.
        hw_profile: The ``HwProfile`` snapshot that produced this plan, kept
            so downstream diagnostic surfaces (Acceleration tab, logs) can
            answer "which probe result drove this choice?" without re-probing.
        reason: Human-readable explanation, e.g.
            ``"RTX 2080 Ti detected -> faster-whisper-cuda"``. Free-form text
            for the Acceleration tab and structured log payload.
    """

    stt_id: str
    diarize_id: str
    llm_id: str
    text_embed_id: str
    hw_profile: HwProfile
    reason: str

    def __post_init__(self) -> None:
        _validate_id("STT", self.stt_id)
        _validate_id("DIARIZE", self.diarize_id)
        _validate_id("LLM", self.llm_id)
        _validate_id("TEXT_EMBED", self.text_embed_id)


def _validate_id(role: str, value: str) -> None:
    """Raise ``ValueError`` if ``value`` is not in ``BACKEND_IDS[role]``."""
    allowed = BACKEND_IDS[role]
    if value not in allowed:
        raise ValueError(
            f"unknown backend id for role {role}: {value!r}. "
            f"Allowed: {sorted(allowed)}"
        )


def is_phase1_implementable(plan: BackendPlan) -> bool:
    """Return ``True`` iff every id in ``plan`` can be built by Phase 1 Factory.

    Phase 1 ships builders for CUDA + CPU only. When the Planner routes to a
    Phase 2 id (e.g. ``openvino-whisper-igpu``) on a host where that backend
    would *be* the right choice, the plan is valid but not yet implementable.
    """
    return (
        plan.stt_id in PHASE1_IMPLEMENTABLE_IDS["STT"]
        and plan.diarize_id in PHASE1_IMPLEMENTABLE_IDS["DIARIZE"]
        and plan.llm_id in PHASE1_IMPLEMENTABLE_IDS["LLM"]
        and plan.text_embed_id in PHASE1_IMPLEMENTABLE_IDS["TEXT_EMBED"]
    )


__all__ = ["PHASE1_IMPLEMENTABLE_IDS", "BackendPlan", "is_phase1_implementable"]

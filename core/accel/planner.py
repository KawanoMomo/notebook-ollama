"""``BackendPlanner`` — pure-data routing from ``HwProfile`` to ``BackendPlan``.

Sprint 2 / Task 2.2 of `docs/superpowers/plans/2026-06-29-igpu-npu-acceleration.md`,
reworked by the spec addendum "Update 2026-08-02" (Phase 1.5).

The planner is intentionally a **pure function** of an ``HwProfile`` snapshot
plus an optional ``BackendOverrides``: no probes, no I/O, no environment
lookups. ``HardwareProbe`` (Sprint 1) is the one component that touches the
OS — the planner only consumes the resulting frozen profile. This split is
what lets the v1 routing rules be table-driven tested across every HW profile
combination without spinning up a real iGPU/NPU.

Routing rules (spec §5 + addendum K1/K2/L):

* STT: CUDA dGPU → ``faster-whisper-cuda``;  Intel iGPU + NPU →
  ``openvino-whisper-npu``;  Intel iGPU only → ``openvino-whisper-igpu``;
  AMD Ryzen AI + DirectML → ``amd-whispercpp-vulkan``;  fallback →
  ``faster-whisper-cpu``.
* DIARIZE: always ``sherpa-onnx-cpu`` (user decision — sherpa-onnx GPU/NPU
  variants are dropped from ``BACKEND_IDS`` entirely).
* LLM: CUDA dGPU → ``ollama-cuda``;  Intel iGPU → ``ollama-vulkan``
  (official Ollama, Vulkan backend default-enabled — addendum K1; the
  archived ipex-llm-ollama path was dropped per addendum K2);
  AMD Ryzen AI → ``ollama-vulkan`` (ROCm does not support Windows APUs;
  Vulkan is the practical iGPU path);  CPU-only → ``ollama-cuda``
  (Ollama auto-degrades to CPU when no GPU is visible).
* TEXT_EMBED: CUDA dGPU → ``ollama-bge-m3-cpu`` (NaN workaround — upstream
  Ollama #13572 was *closed* by a validation-only fix; the underlying GPU
  NaN remains open via #14657 / #16625, so the CPU pin stays. Addendum K4
  also records ``OLLAMA_FLASH_ATTENTION=false`` as a candidate GPU-side
  workaround, pending on-device verification);  Intel iGPU + NPU →
  ``openvino-bge-m3-npu`` (addendum K3: unverified on NPU — treat as PoC
  target, Phase 2 gate);  Intel iGPU only → ``openvino-bge-m3-igpu``;
  fallback → ``ollama-bge-m3-cpu``.
* ``openai-compat`` / ``openai-compat-embed`` are **never auto-selected**.
  They are reachable only through an explicit user override (addendum L) —
  automatic detection cannot know that an OpenAI-compatible server is
  running, let alone where.

NPU contention rule (spec §6.3): an NPU can only be safely owned by a single
process at a time. When STT picks an NPU backend AND TEXT_EMBED would also
pick an NPU backend, the planner degrades TEXT_EMBED — STT is real-time and
keeps the NPU; TEXT_EMBED degrades to iGPU (or CPU if no iGPU).

Overrides (spec §5.1 step 5, addendum M): each role can be forced to a
concrete id via ``BackendOverrides``; the value ``"auto"`` keeps the
planner's pick. Overrides are applied AFTER the automatic selection, so a
forced id wins over every automatic rule **including** the NPU contention
rule — an explicit user choice is authoritative. Validation still applies:
``BackendPlan.__post_init__`` rejects unknown/dropped ids.

Validation is delegated to ``BackendPlan.__post_init__`` (Task 2.1) — every
id the planner emits is checked against ``BACKEND_IDS`` for the matching
role. A bad id surfaces as ``ValueError`` immediately rather than failing
silently downstream when ``BackendFactory`` tries to build it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from core.accel.plan import BackendPlan
from core.accel.profile import HwProfile

AUTO: Final[str] = "auto"


@dataclass(frozen=True)
class BackendOverrides:
    """Per-role user override — ``"auto"`` delegates to the planner.

    Sourced from ``AppConfig`` (``audio.transcriber_backend`` /
    ``audio.diarizer_backend`` / ``ollama.runtime_backend`` /
    ``ollama.text_embed_backend``), all of which default to ``"auto"`` for
    backward compatibility (addendum H).
    """

    stt: str = AUTO
    diarize: str = AUTO
    llm: str = AUTO
    text_embed: str = AUTO


class BackendPlanner:
    """Resolve an ``HwProfile`` (+ optional overrides) into a ``BackendPlan``.

    Stateless and side-effect free. Construct once per process (typical
    pattern — the lifespan / DI wiring creates a single instance) or
    re-construct per call; either is fine.
    """

    def plan(
        self, hw: HwProfile, overrides: BackendOverrides | None = None
    ) -> BackendPlan:
        """Return the ``BackendPlan`` for ``hw``, honouring user overrides."""
        ov = overrides or BackendOverrides()
        stt_id, stt_reason = self._pick_stt(hw)
        diarize_id, diarize_reason = self._pick_diarize(hw)
        llm_id, llm_reason = self._pick_llm(hw)
        text_embed_id, text_embed_reason = self._pick_text_embed(
            hw, avoid_npu=(stt_id == "openvino-whisper-npu")
        )
        stt_id, stt_reason = _apply_override(ov.stt, stt_id, stt_reason)
        diarize_id, diarize_reason = _apply_override(
            ov.diarize, diarize_id, diarize_reason
        )
        llm_id, llm_reason = _apply_override(ov.llm, llm_id, llm_reason)
        text_embed_id, text_embed_reason = _apply_override(
            ov.text_embed, text_embed_id, text_embed_reason
        )
        reason = (
            f"STT: {stt_reason}; "
            f"DIARIZE: {diarize_reason}; "
            f"LLM: {llm_reason}; "
            f"TEXT_EMBED: {text_embed_reason}"
        )
        return BackendPlan(
            stt_id=stt_id,
            diarize_id=diarize_id,
            llm_id=llm_id,
            text_embed_id=text_embed_id,
            hw_profile=hw,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Per-role selectors. Each returns ``(id, reason_fragment)``.
    # ------------------------------------------------------------------

    def _pick_stt(self, hw: HwProfile) -> tuple[str, str]:
        if hw.has_cuda:
            return (
                "faster-whisper-cuda",
                f"CUDA dGPU detected ({hw.dgpu or 'unknown'}) -> faster-whisper-cuda",
            )
        if "NPU" in hw.openvino_devices and "GPU" in hw.openvino_devices:
            return (
                "openvino-whisper-npu",
                "Intel iGPU + NPU detected -> openvino-whisper-npu",
            )
        if "GPU" in hw.openvino_devices:
            return (
                "openvino-whisper-igpu",
                "Intel iGPU detected -> openvino-whisper-igpu",
            )
        if hw.has_directml and _is_amd_host(hw):
            # ``has_directml`` here is a hardware proxy ("Windows + DX12-class
            # GPU present"), not the runtime the backend uses — the whisper.cpp
            # path rides Vulkan (addendum N: DirectML is maintenance-mode and
            # whisper.cpp never had a DML backend).
            return (
                "amd-whispercpp-vulkan",
                f"AMD Ryzen AI detected (ryzen_ai_gen={hw.ryzen_ai_gen}) "
                "-> amd-whispercpp-vulkan",
            )
        return (
            "faster-whisper-cpu",
            "no GPU/NPU acceleration detected -> faster-whisper-cpu",
        )

    def _pick_diarize(self, hw: HwProfile) -> tuple[str, str]:
        # User decision: sherpa-onnx is cpu-only on every host in v1+v2.
        # GPU/NPU variants are dropped from BACKEND_IDS entirely.
        del hw  # explicitly unused — kept for selector symmetry
        return (
            "sherpa-onnx-cpu",
            "diarizer is cpu-only in v1 -> sherpa-onnx-cpu",
        )

    def _pick_llm(self, hw: HwProfile) -> tuple[str, str]:
        if hw.has_cuda:
            return (
                "ollama-cuda",
                f"CUDA dGPU detected ({hw.dgpu or 'unknown'}) -> ollama-cuda",
            )
        if "GPU" in hw.openvino_devices:
            # Addendum K1/K2: ipex-llm-ollama is dropped (archived upstream,
            # known security issues). Official Ollama ships a Vulkan backend
            # (default-enabled since v0.13) that covers Intel iGPUs.
            return (
                "ollama-vulkan",
                "Intel iGPU detected -> ollama-vulkan (official Ollama, "
                "Vulkan backend)",
            )
        if hw.has_directml and _is_amd_host(hw):
            # Addendum K1: ROCm does not support Windows APUs; Vulkan is the
            # practical Radeon iGPU path (780M/880M/890M reports).
            return (
                "ollama-vulkan",
                f"AMD Ryzen AI detected (ryzen_ai_gen={hw.ryzen_ai_gen}) "
                "-> ollama-vulkan (official Ollama, Vulkan backend)",
            )
        # CPU-only host: Ollama auto-degrades to CPU when no GPU is visible,
        # so ``ollama-cuda`` is the right id even though there is no CUDA.
        return (
            "ollama-cuda",
            "no GPU detected -> ollama-cuda (auto-degrades to CPU)",
        )

    def _pick_text_embed(
        self, hw: HwProfile, *, avoid_npu: bool
    ) -> tuple[str, str]:
        if hw.has_cuda:
            # Addendum K4: upstream #13572 is closed but the fix was
            # validation-only; the GPU NaN itself is still open (#14657 /
            # #16625). All CUDA hosts stay pinned to CPU embed.
            return (
                "ollama-bge-m3-cpu",
                "CUDA dGPU detected but GPU embed disabled (Ollama NaN bug, "
                "#13572 closed without root fix; see #14657/#16625) "
                "-> ollama-bge-m3-cpu",
            )
        if (
            "NPU" in hw.openvino_devices
            and "GPU" in hw.openvino_devices
            and not avoid_npu
        ):
            return (
                "openvino-bge-m3-npu",
                "Intel iGPU + NPU detected -> openvino-bge-m3-npu "
                "(addendum K3: unverified on NPU, PoC required)",
            )
        if (
            "NPU" in hw.openvino_devices
            and "GPU" in hw.openvino_devices
            and avoid_npu
        ):
            # NPU contention (spec §6.3): STT already owns the NPU, embed
            # degrades to iGPU.
            return (
                "openvino-bge-m3-igpu",
                "NPU contention: STT owns NPU -> openvino-bge-m3-igpu (degraded)",
            )
        if "GPU" in hw.openvino_devices:
            return (
                "openvino-bge-m3-igpu",
                "Intel iGPU detected -> openvino-bge-m3-igpu",
            )
        return (
            "ollama-bge-m3-cpu",
            "no Intel iGPU/NPU detected -> ollama-bge-m3-cpu",
        )


def _apply_override(
    override: str, auto_id: str, auto_reason: str
) -> tuple[str, str]:
    """Return ``(id, reason)`` after applying a per-role user override.

    ``"auto"`` (or empty) keeps the planner's pick; anything else replaces
    it verbatim. Id validity is enforced downstream by
    ``BackendPlan.__post_init__``.
    """
    if not override or override == AUTO:
        return auto_id, auto_reason
    return override, f"user override -> {override}"


# Ryzen AI chip family names emitted by ``probe_amd_npu`` (spec §2). Used by
# ``_is_amd_host`` to decide whether the AMD-path routing rules apply.
_AMD_NPU_CHIPS: Final[frozenset[str]] = frozenset(
    {"phoenix", "hawk_point", "strix", "krackan_point"}
)


def _is_amd_host(hw: HwProfile) -> bool:
    """True iff ``hw`` looks like an AMD Ryzen AI host.

    Signals (any one is sufficient):

    * ``vendor == "amd"`` — set by ``HardwareProbe`` when ``probe_amd_npu``
      returns a chip family.
    * ``ryzen_ai_gen`` is not ``None`` — derived from the same probe.
    * ``npu`` is one of the AMD chip family names — defensive fallback for
      test fixtures that only populate one of the AMD fields.
    """
    if hw.vendor == "amd":
        return True
    if hw.ryzen_ai_gen is not None:
        return True
    return hw.npu in _AMD_NPU_CHIPS


__all__ = ["BackendOverrides", "BackendPlanner"]

"""``BackendPlanner`` — pure-data routing from ``HwProfile`` to ``BackendPlan``.

Sprint 2 / Task 2.2 of `docs/superpowers/plans/2026-06-29-igpu-npu-acceleration.md`.

The planner is intentionally a **pure function** of an ``HwProfile`` snapshot:
no probes, no I/O, no environment lookups. ``HardwareProbe`` (Sprint 1) is
the one component that touches the OS — the planner only consumes the
resulting frozen profile. This split is what lets the v1 routing rules be
table-driven tested across every HW profile combination without spinning up
a real iGPU/NPU.

Routing rules (spec §5 + Task 2.2 description):

* STT: CUDA dGPU → ``faster-whisper-cuda``;  Intel iGPU + NPU →
  ``openvino-whisper-npu``;  Intel iGPU only → ``openvino-whisper-igpu``;
  AMD Ryzen AI + DirectML → ``amd-whispercpp-dml``;  fallback →
  ``faster-whisper-cpu``.
* DIARIZE: always ``sherpa-onnx-cpu`` (user decision — sherpa-onnx GPU/NPU
  variants are dropped from ``BACKEND_IDS`` entirely).
* LLM: CUDA dGPU → ``ollama-cuda``;  Intel iGPU → ``ipex-llm-ollama``;
  AMD DirectML → ``ollama-directml``;  CPU-only → ``ollama-cuda``
  (Ollama auto-degrades to CPU when no GPU is visible).
* TEXT_EMBED: CUDA dGPU → ``ollama-bge-m3-cpu`` (NaN bug workaround — GPU
  embed is disabled until upstream Ollama #13572 lands);  Intel iGPU + NPU →
  ``openvino-bge-m3-npu``;  Intel iGPU only → ``openvino-bge-m3-igpu``;
  fallback → ``ollama-bge-m3-cpu``.

NPU contention rule (spec §6.3): an NPU can only be safely owned by a single
process at a time. When STT picks an NPU backend AND TEXT_EMBED would also
pick an NPU backend, the planner degrades TEXT_EMBED — STT is real-time and
keeps the NPU; TEXT_EMBED degrades to iGPU (or CPU if no iGPU).

Validation is delegated to ``BackendPlan.__post_init__`` (Task 2.1) — every
id the planner emits is checked against ``BACKEND_IDS`` for the matching
role. A bad id surfaces as ``ValueError`` immediately rather than failing
silently downstream when ``BackendFactory`` tries to build it.
"""

from __future__ import annotations

from typing import Final

from core.accel.plan import BackendPlan
from core.accel.profile import HwProfile


class BackendPlanner:
    """Resolve an ``HwProfile`` into a concrete ``BackendPlan``.

    Stateless and side-effect free. Construct once per process (typical
    pattern — the lifespan / DI wiring creates a single instance) or
    re-construct per call; either is fine.
    """

    def plan(self, hw: HwProfile) -> BackendPlan:
        """Return the ``BackendPlan`` the planner picks for ``hw``."""
        stt_id, stt_reason = self._pick_stt(hw)
        diarize_id, diarize_reason = self._pick_diarize(hw)
        llm_id, llm_reason = self._pick_llm(hw)
        text_embed_id, text_embed_reason = self._pick_text_embed(
            hw, avoid_npu=(stt_id == "openvino-whisper-npu")
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
            return (
                "amd-whispercpp-dml",
                f"AMD Ryzen AI + DirectML detected (ryzen_ai_gen={hw.ryzen_ai_gen}) "
                "-> amd-whispercpp-dml",
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
            return (
                "ipex-llm-ollama",
                "Intel iGPU detected -> ipex-llm-ollama",
            )
        if hw.has_directml and _is_amd_host(hw):
            return (
                "ollama-directml",
                f"AMD Ryzen AI + DirectML detected (ryzen_ai_gen={hw.ryzen_ai_gen}) "
                "-> ollama-directml",
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
            # Spec §4.4: GPU embed is disabled due to upstream NaN bug
            # (Ollama #13572). All CUDA hosts pin to CPU embed for now.
            return (
                "ollama-bge-m3-cpu",
                "CUDA dGPU detected but GPU embed disabled (Ollama #13572 NaN bug) "
                "-> ollama-bge-m3-cpu",
            )
        if (
            "NPU" in hw.openvino_devices
            and "GPU" in hw.openvino_devices
            and not avoid_npu
        ):
            return (
                "openvino-bge-m3-npu",
                "Intel iGPU + NPU detected -> openvino-bge-m3-npu",
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


__all__ = ["BackendPlanner"]

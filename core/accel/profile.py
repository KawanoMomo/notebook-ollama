"""Canonical ``HwProfile`` dataclass and ``_STUB_PROFILE`` constant.

Sprint 1 / Task 1.6 of `docs/superpowers/plans/2026-06-29-igpu-npu-acceleration.md`.

Lives in its own module (not in ``core/accel/__init__.py``) so that:

* ``core.accel.probe.HardwareProbe`` and downstream Phase 2 modules
  (``core.accel.planner`` / ``core.accel.factory``) can import the dataclass
  cheaply without triggering re-execution of ``__init__`` side-effects;
* ``core.accel.probe_env`` keeps depending on ``_STUB_PROFILE`` via the
  ``__init__`` re-export, preserving backward-compat with the Wave 2 import
  surface (``from core.accel import _STUB_PROFILE, HwProfile``).

Field set is the canonical Phase 1 list per the spec addendum (§A) — the
pre-addendum §3.1 list is overridden by that addendum. ``vendor`` is added
here as a derived discriminator (``"nvidia" | "intel" | "amd" | "unknown"``)
so callers can switch on a single string without re-implementing the priority
logic that ``HardwareProbe.run()`` already encodes (CUDA > AMD NPU > OpenVINO
GPU/NPU > unknown).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HwProfile:
    """Snapshot of detected accelerators on the host machine.

    All fields are immutable. Instances are produced exclusively by
    ``core.accel.probe.HardwareProbe.run()`` (Task 1.6) or the
    ``_STUB_PROFILE`` constant below.

    Fields:
        vendor: Derived discriminator chosen by ``HardwareProbe.run()`` —
            one of ``"nvidia"``, ``"intel"``, ``"amd"``, or ``"unknown"``.
            Priority: CUDA > AMD NPU > Intel OpenVINO GPU/NPU > unknown.
        cpu_brand: Marketing name (``"12th Gen Intel(R) Core(TM) i9-12900KF"``)
            or ``"unknown"`` if no source could resolve it. Never contains
            hostname / IP / MAC / serial (privacy guarantee, enforced by
            ``test_pii_excluded``).
        dgpu: NVIDIA dGPU name reported by ``nvidia-smi``, or ``None``.
        igpu: Coarse iGPU label inferred from ``openvino_devices`` —
            ``"Intel iGPU"`` when OpenVINO exposes ``"GPU"``, else ``None``.
            AMD iGPUs are not detected in Phase 1 (no DML/openvino path).
        npu: Friendly NPU label — ``"Intel NPU"`` (when OpenVINO exposes
            ``"NPU"``) or one of ``"phoenix" | "hawk_point" | "strix" |
            "krackan_point"`` (raw chip family from ``probe_amd_npu``), or
            ``None``.
        vram_mb: dGPU VRAM in MiB as reported by ``nvidia-smi``, or ``None``.
            iGPU/NPU VRAM is not probed in Phase 1.
        ryzen_ai_gen: XDNA generation (``1`` for Phoenix/Hawk Point, ``2`` for
            Strix/Krackan Point), or ``None`` for non-AMD-NPU hosts.
        openvino_devices: Tuple of OpenVINO device names (e.g.
            ``("CPU", "GPU", "NPU")``). Empty tuple when the openvino wheel
            is not installed (Phase 1 default).
        has_directml: True iff ``onnxruntime`` exposes
            ``DmlExecutionProvider`` — used by Phase 2 sherpa-onnx / ORT paths.
        has_cuda: True iff ``ctranslate2.get_cuda_device_count() > 0`` after
            the C1 DLL-search-path registration ran. Mirrors
            ``cuda_device_count > 0`` but is kept as an explicit bool so
            callers do not have to redo the comparison.
        cuda_device_count: Number of CUDA devices visible to ctranslate2.
    """

    vendor: str
    cpu_brand: str
    dgpu: str | None
    igpu: str | None
    npu: str | None
    vram_mb: int | None
    ryzen_ai_gen: int | None
    openvino_devices: tuple[str, ...]
    has_directml: bool
    has_cuda: bool
    cuda_device_count: int


# Fixed stub returned when NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE=1 is set.
# Represents a CPU-only machine with no GPU/NPU acceleration, so downstream
# Planner picks CPU backends without any real probes firing.
#
# IMPORTANT: ``cpu_brand="test"`` is asserted by
# ``tests/unit/test_probe_env.py::TestStubProfile::test_stub_profile_field_values``
# — do not rename the literal without updating that test.
_STUB_PROFILE: HwProfile = HwProfile(
    vendor="unknown",
    cpu_brand="test",
    dgpu=None,
    igpu=None,
    npu=None,
    vram_mb=None,
    ryzen_ai_gen=None,
    openvino_devices=(),
    has_directml=False,
    has_cuda=False,
    cuda_device_count=0,
)


__all__ = ["_STUB_PROFILE", "HwProfile"]

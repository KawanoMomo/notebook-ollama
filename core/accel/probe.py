"""Individual hardware-detection probes + ``HardwareProbe`` orchestrator.

Sprint 1 / Tasks 1.4 + 1.6 of
`docs/superpowers/plans/2026-06-29-igpu-npu-acceleration.md`.

Each probe is independent and returns a single piece consumed by ``HwProfile``
(defined in ``core.accel.profile``). They are deliberately kept as free
functions (not methods on ``HardwareProbe``) so:

* the unit tests can mock them individually with ``patch("core.accel.probe.X")``;
* ``HardwareProbe.run()`` can compose them without inheritance gymnastics;
* ``probe_cuda()`` (added in Task 1.3 in ``core.accel.probe_cuda``) can sit
  alongside without importing ``faster-whisper`` (DLL search-path registration
  is delegated to ``core.accel.cuda_dll``).

``HardwareProbe`` (Task 1.6) ties the probes together into a frozen
``HwProfile`` snapshot. It is thread-safe and idempotent: ``run()`` caches
its first successful result and serves subsequent callers from the cache
until ``clear_cache()`` is invoked. This guarantees that lifespan / DI code
(Sprint 3) can call ``run()`` from multiple workers without re-shelling out
to ``pnputil`` / re-importing ``ctranslate2``.

INVARIANTS (enforced by tests):

* Each probe times out within 5 seconds in production.
* No probe ever raises — failure returns ``None`` / empty / sentinel.
* No probe includes hostname / IP / MAC / serial in its output (privacy).
* ``subprocess`` / ``winreg`` / ``onnxruntime`` / ``openvino`` are imported
  at the module level (or via ``sys.modules`` lookup) so they can be patched
  cleanly in tests.
* ``HardwareProbe.run()`` short-circuits to the fixed ``_STUB_PROFILE`` when
  ``NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE=1`` is set — no sub-probe is invoked.
"""

from __future__ import annotations

import platform
import re
import subprocess
import sys
import threading
from typing import Any

from core.accel.probe_cuda import probe_cuda
from core.accel.probe_env import should_skip_probe
from core.accel.profile import _STUB_PROFILE, HwProfile

__all__ = [
    "HardwareProbe",
    "probe_amd_npu",
    "probe_cpu",
    "probe_cuda",
    "probe_dgpu",
    "probe_directml",
    "probe_openvino_devices",
]

# Conservative timeout for every external shell-out. Spec §3.1 lists pnputil and
# nvidia-smi as the probes that actually exec a binary; both return well under
# a second on a healthy box. 5 s is enough headroom for a sleepy laptop without
# blocking app startup.
_PROBE_TIMEOUT_SEC = 5

# pnputil `Instance ID:` line shape per spec §2:
#   PCI\VEN_1022&DEV_1502&SUBSYS_xxxxxxxx&REV_00\<instance-tail>
# REV is mandatory in real output; we still accept its absence to be defensive.
_AMD_RE = re.compile(
    r"VEN_1022&DEV_(?P<dev>[0-9A-F]{4})(?:[^\\\r\n]*REV_(?P<rev>[0-9A-F]{2}))?",
    re.IGNORECASE,
)

# AMD Ryzen mobile SKU pattern. Phoenix (7040 series) ships SKUs like
# "Ryzen 7 7840U", "Ryzen 9 7940HS"; Hawk Point (8040 series) ships
# "Ryzen 7 8840U", "Ryzen 9 8945HX". Both share PCI ID VEN_1022&DEV_1502 so
# the leading digit of the 4-digit SKU is the only reliable discriminator.
_RYZEN_SKU_RE = re.compile(r"ryzen\s+\d+\s+(?P<series>[78])\d{3}")


# -----------------------------------------------------------------------------
# probe_cpu
# -----------------------------------------------------------------------------


def probe_cpu() -> str:
    """Return the CPU brand string (e.g. "12th Gen Intel(R) Core(TM) i9-12900KF").

    Order of preference:

    1. Windows registry ``HARDWARE\\DESCRIPTION\\System\\CentralProcessor\\0`` /
       ``ProcessorNameString`` — accurate, no shell-out.
    2. ``platform.processor()`` — coarse fallback (often the family name).
    3. Sentinel ``"unknown"`` — if even ``platform.processor()`` raises or
       returns empty.

    NEVER includes hostname / MAC / serial. The registry read is scoped to a
    single value name.
    """
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            )
            try:
                brand, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            finally:
                try:
                    winreg.CloseKey(key)
                except Exception:  # noqa: S110 — defensive close, never re-raise
                    pass
            brand_s = str(brand).strip()
            if brand_s:
                return brand_s
        except Exception:  # noqa: S110 — fall through to platform.processor()
            pass

    try:
        proc = platform.processor() or ""
        proc_s = proc.strip()
        return proc_s or "unknown"
    except Exception:
        return "unknown"


# -----------------------------------------------------------------------------
# probe_dgpu (NVIDIA-only — CUDA dGPU detection)
# -----------------------------------------------------------------------------


def probe_dgpu() -> dict[str, Any] | None:
    """Detect an NVIDIA CUDA dGPU via ``nvidia-smi``. Returns ``None`` if absent.

    Output shape: ``{"name": str, "vram_mb": int}`` for the first GPU.

    Failure modes (all return ``None`` silently):

    * ``nvidia-smi`` binary not on PATH (``FileNotFoundError``).
    * Non-zero exit (driver mismatch, GPU in error state).
    * Malformed / empty stdout (driver crashed mid-query).
    * Timeout (``> _PROBE_TIMEOUT_SEC``).
    * Any other unexpected exception (defensive — no exception escapes).
    """
    # nvidia-smi is intentionally resolved from PATH (it ships with the NVIDIA
    # driver in System32 on Windows; no fixed install path exists across vendors).
    cmd = ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]
    try:
        result = subprocess.run(  # noqa: S603 — fixed argv, no shell, no user input
            cmd,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SEC,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    except Exception:
        return None

    if result.returncode != 0:
        return None

    stdout = (result.stdout or "").strip()
    if not stdout:
        return None

    first_line = stdout.splitlines()[0].strip()
    if "," not in first_line:
        return None

    name_part, _, vram_part = first_line.partition(",")
    name = name_part.strip()
    vram_raw = vram_part.strip()
    if not name or not vram_raw:
        return None

    try:
        vram_mb = int(float(vram_raw))
    except (TypeError, ValueError):
        return None

    return {"name": name, "vram_mb": vram_mb}


# -----------------------------------------------------------------------------
# probe_directml
# -----------------------------------------------------------------------------


def probe_directml() -> bool:
    """Return True iff ``onnxruntime`` exposes ``DmlExecutionProvider``.

    Per the plan, DXCore enumeration via ``ctypes`` is intentionally avoided in
    Phase 1: the only signal we actually need downstream is "can we route
    sherpa-onnx / future ORT loads through DirectML?", and the cheapest reliable
    answer is to ask ``onnxruntime`` itself.

    DirectML is Windows-only. On non-Windows the answer is always False without
    importing ``onnxruntime`` (saves a multi-MB import on Linux CI).
    """
    if sys.platform != "win32":
        return False
    try:
        import onnxruntime as ort
    except Exception:
        return False
    try:
        providers = ort.get_available_providers()
    except Exception:
        return False
    return "DmlExecutionProvider" in providers


# -----------------------------------------------------------------------------
# probe_amd_npu (AMD Ryzen AI NPU detection via pnputil)
# -----------------------------------------------------------------------------


def probe_amd_npu(cpu_brand: str | None = None) -> str | None:
    """Detect the AMD Ryzen AI NPU chip family. Returns one of:

    * ``"phoenix"``       — XDNA1, ``VEN_1022&DEV_1502`` (Ryzen 7040 series)
    * ``"hawk_point"``    — XDNA1, same PCI ID, distinguished by ``cpu_brand``
                            containing ``"8040"`` (Ryzen 8040 series)
    * ``"strix"``         — XDNA2, ``VEN_1022&DEV_17F0&REV_00/10/11``
                            (covers Strix Point + Strix Halo; per spec §2 they
                            share the PCI ID family)
    * ``"krackan_point"`` — XDNA2, ``VEN_1022&DEV_17F0&REV_20``
    * ``None``            — no AMD NPU detected, or non-Windows, or failure.

    Phoenix vs Hawk Point cannot be distinguished by PCI ID alone (spec §2).
    Pass ``cpu_brand`` (typically the return value of :func:`probe_cpu`) to
    disambiguate; missing brand defaults to ``"phoenix"`` (older / more common).

    Failure modes (all return ``None`` silently):
    non-Windows, missing pnputil binary, non-zero exit, malformed output,
    timeout, any unexpected exception.
    """
    if sys.platform != "win32":
        return None

    # pnputil ships with Windows in System32 — resolved from PATH by convention.
    cmd = ["pnputil", "/enum-devices", "/bus", "PCI", "/deviceids"]
    try:
        result = subprocess.run(  # noqa: S603 — fixed argv, no shell, no user input
            cmd,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SEC,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    except Exception:
        return None

    if result.returncode != 0:
        return None

    output = result.stdout or ""
    if not output:
        return None

    brand_lc = (cpu_brand or "").lower()

    for match in _AMD_RE.finditer(output):
        dev = match.group("dev").upper()
        rev = (match.group("rev") or "").upper()

        if dev == "1502":
            # Phoenix (Ryzen 7040) and Hawk Point (Ryzen 8040) share this PCI
            # ID — disambiguate by the leading digit of the CPU SKU when the
            # caller supplies a brand string (e.g. "AMD Ryzen 7 8840U").
            sku_match = _RYZEN_SKU_RE.search(brand_lc)
            if sku_match and sku_match.group("series") == "8":
                return "hawk_point"
            return "phoenix"

        if dev == "17F0":
            if rev == "20":
                return "krackan_point"
            # REV 00/10/11 (and unknown rev) → Strix Point / Strix Halo family.
            return "strix"

    return None


# -----------------------------------------------------------------------------
# probe_openvino_devices (Intel iGPU/NPU enumeration)
# -----------------------------------------------------------------------------


def probe_openvino_devices() -> tuple[str, ...]:
    """Return ``openvino.Core().available_devices`` as a tuple.

    Returns an empty tuple on:

    * ``openvino`` wheel not installed (Phase 1 default — no Intel extras).
    * ``Core()`` construction failure (driver in error state).
    * any unexpected exception during enumeration.

    Typical non-empty values seen on real hardware:

    * Intel CPU-only: ``("CPU",)``
    * Intel Meteor / Lunar / Arrow Lake: ``("CPU", "GPU", "NPU")``
    * Intel iGPU only (older NPU drv missing): ``("CPU", "GPU")``

    The probe is intentionally a thin wrapper — Phase 2 will introduce
    ``Vendor`` discrimination and ``compute_capability`` parsing elsewhere.
    """
    try:
        import openvino  # type: ignore[import-not-found]
    except Exception:
        return ()
    try:
        core = openvino.Core()
        return tuple(core.available_devices)
    except Exception:
        return ()


# -----------------------------------------------------------------------------
# HardwareProbe orchestrator (Task 1.6)
# -----------------------------------------------------------------------------


# Mapping from ``probe_amd_npu`` chip families to XDNA generation (per spec §2).
# Phoenix / Hawk Point share PCI ID VEN_1022&DEV_1502 — both are XDNA1.
# Strix / Strix Halo / Krackan Point all have VEN_1022&DEV_17F0 — all XDNA2.
_AMD_NPU_GEN: dict[str, int] = {
    "phoenix": 1,
    "hawk_point": 1,
    "strix": 2,
    "krackan_point": 2,
}


class HardwareProbe:
    """Compose the 6 sub-probes into a single :class:`HwProfile` snapshot.

    Lifecycle:

    * ``run()`` returns ``_STUB_PROFILE`` immediately when
      ``NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE=1`` — no sub-probe is invoked. The
      stub result is **not** cached; toggling the env var between calls is
      expected to take effect on the next ``run()``.
    * Otherwise, the first call invokes every sub-probe once, assembles a
      frozen :class:`HwProfile`, caches it, and returns it.
    * Subsequent calls return the cached profile (identity-equal — the
      ``is`` check in ``test_run_is_cached`` relies on this).
    * ``clear_cache()`` discards the cached profile; the next ``run()`` will
      re-invoke the sub-probes from scratch.

    Thread safety:

    * A single :class:`threading.Lock` serialises cache reads/writes so that
      concurrent ``run()`` calls do not race. The lock is released around
      each sub-probe call only after the first thread completes — by design
      this serialises probe work, but probes are short (<5 s each) and a
      single probe pass per process is the steady state, so contention is
      a non-issue in practice.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: HwProfile | None = None

    def run(self) -> HwProfile:
        """Return a (possibly cached) :class:`HwProfile` for this host."""
        with self._lock:
            if self._cache is not None:
                return self._cache

            if should_skip_probe():
                # Intentionally NOT cached: tests/integration fixtures flip
                # the env var around individual tests, so the next call
                # must observe the current env state. _STUB_PROFILE is a
                # module-level singleton so returning it repeatedly is free.
                return _STUB_PROFILE

            profile = _build_profile()
            self._cache = profile
            return profile

    def clear_cache(self) -> None:
        """Discard the cached profile so the next ``run()`` re-probes."""
        with self._lock:
            self._cache = None


def _build_profile() -> HwProfile:
    """Invoke every sub-probe and assemble the resulting :class:`HwProfile`.

    Extracted from ``HardwareProbe.run`` so it can be unit-tested directly
    without going through the lock / cache machinery, and so the cache code
    path stays readable.
    """
    cpu_brand = probe_cpu()
    has_cuda, cuda_n = probe_cuda()
    dgpu_info = probe_dgpu()
    has_directml = probe_directml()
    amd_npu_chip = probe_amd_npu(cpu_brand=cpu_brand)
    ov_devices = probe_openvino_devices()

    # ---- derive higher-level fields -----------------------------------
    dgpu_name = dgpu_info["name"] if dgpu_info else None
    vram_mb = dgpu_info["vram_mb"] if dgpu_info else None

    igpu = "Intel iGPU" if "GPU" in ov_devices else None

    # NPU label priority: Intel OpenVINO NPU > AMD chip family.
    # Spec §6.3 forbids using both NPUs at once anyway; choosing the Intel
    # label here keeps the Planner's "single NPU consumer" rule trivial.
    npu: str | None = None
    if "NPU" in ov_devices:
        npu = "Intel NPU"
    elif amd_npu_chip is not None:
        npu = amd_npu_chip

    ryzen_ai_gen = _AMD_NPU_GEN.get(amd_npu_chip) if amd_npu_chip else None

    # Vendor priority: CUDA > AMD NPU > Intel openvino GPU/NPU > unknown.
    # This is the same priority Planner uses to pick a backend in Sprint 2
    # so callers can switch on this single string without re-deriving it.
    if has_cuda:
        vendor = "nvidia"
    elif amd_npu_chip is not None:
        vendor = "amd"
    elif "GPU" in ov_devices or "NPU" in ov_devices:
        vendor = "intel"
    else:
        vendor = "unknown"

    return HwProfile(
        vendor=vendor,
        cpu_brand=cpu_brand,
        dgpu=dgpu_name,
        igpu=igpu,
        npu=npu,
        vram_mb=vram_mb,
        ryzen_ai_gen=ryzen_ai_gen,
        openvino_devices=tuple(ov_devices),
        has_directml=has_directml,
        has_cuda=has_cuda,
        cuda_device_count=cuda_n,
    )

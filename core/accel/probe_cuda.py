"""CUDA availability probe (Sprint 1 / Task 1.3).

Returns ``(available, device_count)`` by calling
``ctranslate2.get_cuda_device_count()`` after registering the CUDA DLL search
directories. The DLL-dir registration is delegated to
``core.accel.cuda_dll._register_cuda_dll_dirs`` (extracted in Task 1.1) so
this module does NOT depend on ``faster-whisper`` / ``core.recording.transcriber``,
which would create a circular import once the BackendFactory wires
``HardwareProbe`` into FastAPI dependencies in Sprint 3.

CRITICAL — C1 fix
-----------------
``_register_cuda_dll_dirs()`` MUST run BEFORE ``ctranslate2`` is imported on
Windows. Skipping it under a clean ``uv run python`` causes ctranslate2 to
silently report 0 devices because ``cudnn_ops_infer64_8.dll`` /
``cublas64_12.dll`` fail to load (their dependencies are not on PATH and have
not been registered via ``os.add_dll_directory``). The Planner then falls
back to CPU and the user sees mysteriously slow transcription on a perfectly
healthy CUDA box.

The unit-test ``tests/unit/test_probe_cuda.py::
test_probe_cuda_calls_register_dll_dirs_before_import`` is the dedicated
regression guard for that ordering.

We import ``ctranslate2`` via ``importlib.import_module`` (not a top-level
``import`` statement) for two reasons:

1. The ordering test can interpose on the function cleanly.
2. The probe is a lazy operation — pulling ctranslate2 at import time would
   inflate startup cost (and break Linux CI where the wheel isn't installed)
   for callers who never invoke ``probe_cuda()``.
"""
from __future__ import annotations

import importlib

from core.accel.cuda_dll import _register_cuda_dll_dirs

__all__ = ["probe_cuda"]


def probe_cuda() -> tuple[bool, int]:
    """Return ``(cuda_available, device_count)``.

    Returns ``(False, 0)`` silently on any failure — never raises. The Planner
    treats a False here as "no CUDA" and selects a CPU backend, which is the
    correct user-visible behaviour for a machine without CUDA installed.

    Failure modes that all map to ``(False, 0)``:

    * ``ImportError`` — ``ctranslate2`` wheel not installed.
    * ``OSError`` at import time — DLL load failure (missing cuDNN / cublas
      on Windows; e.g. C1 fix not applied or driver corrupted).
    * ``OSError`` at runtime — ``get_cuda_device_count()`` crashes in the
      CUDA runtime (driver mismatch, GPU in error state).
    * Any other exception from ``get_cuda_device_count()`` — defensive
      catch-all so no probe exception ever escapes to the caller.
    """
    # C1 fix: DLL search dirs MUST be registered BEFORE the ctranslate2 import,
    # and MUST be registered even if the import subsequently fails (so the
    # next caller on the same process doesn't re-hit the same DLL-load error
    # — see test_probe_cuda_register_dll_dirs_still_called_even_on_import_failure).
    _register_cuda_dll_dirs()

    try:
        ctranslate2 = importlib.import_module("ctranslate2")
    except (ImportError, OSError):
        return (False, 0)

    try:
        n = int(ctranslate2.get_cuda_device_count())
    except Exception:
        # Defensive catch-all: any cuda runtime error (driver mismatch, GPU
        # in error state) maps to no-cuda. Never let an exception escape.
        return (False, 0)

    return (n > 0, n)

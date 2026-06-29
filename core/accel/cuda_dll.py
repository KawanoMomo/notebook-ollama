"""CUDA DLL search-path registration helper (shared, no circular import).

Phase 1 / Sprint 1 / Task 1.1.

Historically this lived inside ``core/recording/transcriber.py`` as a vendored
copy of meeting-transcriber's ``app._cuda_dll`` module. It is now extracted to
``core.accel.cuda_dll`` so the upcoming ``core.accel.probe.probe_cuda()`` can
register the DLL search dirs **before** importing ``ctranslate2`` without
pulling ``faster_whisper`` (and its heavy CUDA/cuDNN imports) into the probe
path. Keeping it in ``transcriber`` would create a circular import once the
probe module ships in Sprint 1 Task 1.3.

The function is a no-op on non-Windows or when the ``nvidia-*`` wheels are
absent. It is idempotent at the module level: calling it twice does not
re-register the same directory, which lets ``transcriber.py`` keep its
import-time call while ``probe_cuda()`` also calls it on every probe.
"""
from __future__ import annotations

import importlib.util
import os
import sys

__all__ = ["_register_cuda_dll_dirs"]

# Bin dirs already passed to ``os.add_dll_directory`` in this process. Used to
# make ``_register_cuda_dll_dirs()`` idempotent. Reset only from test fixtures.
_REGISTERED_DIRS: set[str] = set()


def _register_cuda_dll_dirs() -> list[str]:
    """Register ``site-packages/nvidia/*/bin`` with ``os.add_dll_directory``.

    Returns the cumulative list of bin dirs registered in this process (not
    just the ones newly added by this call), so callers can introspect the
    final state. Returns an empty list when:

    * we are not running on Windows, or
    * ``os.add_dll_directory`` is unavailable, or
    * the ``nvidia`` namespace package cannot be located.

    The function is idempotent — repeated calls do not invoke
    ``os.add_dll_directory`` more than once per unique directory.
    """
    if sys.platform != "win32" or not hasattr(os, "add_dll_directory"):
        return []

    try:
        spec = importlib.util.find_spec("nvidia")
    except Exception:
        return list(_REGISTERED_DIRS)

    if spec is None or not spec.submodule_search_locations:
        return list(_REGISTERED_DIRS)

    base = next(iter(spec.submodule_search_locations))  # .../site-packages/nvidia
    try:
        subdirs = sorted(os.listdir(base))
    except OSError:
        return list(_REGISTERED_DIRS)

    newly_added: list[str] = []
    for sub in subdirs:
        d = os.path.join(base, sub, "bin")
        if not os.path.isdir(d):
            continue
        if d in _REGISTERED_DIRS:
            continue
        try:
            os.add_dll_directory(d)
        except OSError:
            # Hardware/driver mismatch — surface as "this dir wasn't registered"
            # rather than crashing the probe / transcriber init.
            continue
        _REGISTERED_DIRS.add(d)
        newly_added.append(d)

    if newly_added:
        # ``add_dll_directory`` alone is insufficient on this CUDA stack —
        # ctranslate2 cannot resolve ``cublas64_12.dll``'s transitive deps
        # without PATH. Mirror what meeting-transcriber's ``start-gpu.bat``
        # does, but in-process so a plain ``uvicorn`` launch gets GPU too.
        os.environ["PATH"] = (
            os.pathsep.join(newly_added) + os.pathsep + os.environ.get("PATH", "")
        )

    return list(_REGISTERED_DIRS)

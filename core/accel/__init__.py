"""Hardware acceleration probe / planner / factory package.

Phase 1 scope: hardware detection skeleton + CUDA baseline gate.
See `docs/superpowers/plans/2026-06-29-igpu-npu-acceleration.md`.

This ``__init__`` re-exports the canonical ``HwProfile`` dataclass and the
fixed ``_STUB_PROFILE`` (now defined in ``core.accel.profile`` — Task 1.6)
to preserve the Wave 2 import surface (``from core.accel import HwProfile,
_STUB_PROFILE``) that ``core.accel.probe_env`` and
``tests/unit/test_probe_env.py`` rely on.
"""

from __future__ import annotations

from core.accel.profile import _STUB_PROFILE, HwProfile

__all__ = ["_STUB_PROFILE", "HwProfile"]

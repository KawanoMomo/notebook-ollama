"""Unit tests for `core.accel.probe_cuda.probe_cuda` (Sprint 1 / Task 1.3).

C1 critical-fix coverage:

The CUDA DLL search-path registration MUST happen BEFORE `ctranslate2` is
imported. Skipping this on Windows causes `ctranslate2` to silently report 0
devices because `cudnn_ops_infer64_8.dll` / `cublas64_12.dll` fail to load
under a clean `uv run python` (no shell-level PATH munging). Result: Planner
falls back to CPU even when CUDA is fully installed.

`test_probe_cuda_calls_register_dll_dirs_before_import` is the dedicated
regression test for that fix — it captures call ordering by interposing on
both `_register_cuda_dll_dirs` and `importlib.import_module("ctranslate2")`.

All other tests cover the documented failure modes:
- ImportError on ctranslate2 → (False, 0)
- OSError on the import (DLL load failure) → (False, 0)
- OSError raised by get_cuda_device_count at runtime → (False, 0)
- get_cuda_device_count returning 0 → (False, 0)
- get_cuda_device_count returning N>0 → (True, N)

No real CUDA / ctranslate2 import is exercised — `importlib.import_module` is
patched at the module boundary so these tests run on any host (Linux CI too).
"""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest

# --------------------------------------------------------------------------- #
# C1 fix: register-before-import ordering                                     #
# --------------------------------------------------------------------------- #


def test_probe_cuda_calls_register_dll_dirs_before_import(monkeypatch):
    """C1 fix: `_register_cuda_dll_dirs()` must run BEFORE `ctranslate2` is imported.

    If this ordering breaks, a clean `uv run python` on Windows loads
    `ctranslate2` without cuDNN/cublas on the DLL search path, and
    `get_cuda_device_count()` silently returns 0 → Planner picks CPU.

    The order is captured by appending to `call_order` from both interposers
    and asserting the exact sequence.
    """
    from core.accel import probe_cuda as probe_cuda_mod

    call_order: list[str] = []

    def fake_register() -> list[str]:
        call_order.append("register")
        return []

    fake_ct2 = MagicMock()
    fake_ct2.get_cuda_device_count.return_value = 1

    real_import = importlib.import_module

    def fake_import(name: str, *args, **kwargs):
        if name == "ctranslate2":
            call_order.append("import")
            return fake_ct2
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(probe_cuda_mod, "_register_cuda_dll_dirs", fake_register)
    monkeypatch.setattr(probe_cuda_mod.importlib, "import_module", fake_import)

    probe_cuda_mod.probe_cuda()

    assert call_order == ["register", "import"], (
        f"C1 fix broken: expected ['register', 'import'] in that order, "
        f"got {call_order}"
    )


# --------------------------------------------------------------------------- #
# Happy path                                                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("device_count", [1, 2, 4])
def test_probe_cuda_returns_true_and_count_when_devices_present(
    monkeypatch, device_count
):
    """Happy path: ctranslate2 reports N>0 devices → (True, N)."""
    from core.accel import probe_cuda as probe_cuda_mod

    fake_ct2 = MagicMock()
    fake_ct2.get_cuda_device_count.return_value = device_count

    real_import = importlib.import_module

    def fake_import(name: str, *args, **kwargs):
        if name == "ctranslate2":
            return fake_ct2
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(probe_cuda_mod, "_register_cuda_dll_dirs", lambda: [])
    monkeypatch.setattr(probe_cuda_mod.importlib, "import_module", fake_import)

    ok, n = probe_cuda_mod.probe_cuda()
    assert ok is True
    assert n == device_count


def test_probe_cuda_returns_false_when_device_count_is_zero(monkeypatch):
    """No CUDA devices visible → (False, 0). Driver loaded but no GPU."""
    from core.accel import probe_cuda as probe_cuda_mod

    fake_ct2 = MagicMock()
    fake_ct2.get_cuda_device_count.return_value = 0

    real_import = importlib.import_module

    def fake_import(name: str, *args, **kwargs):
        if name == "ctranslate2":
            return fake_ct2
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(probe_cuda_mod, "_register_cuda_dll_dirs", lambda: [])
    monkeypatch.setattr(probe_cuda_mod.importlib, "import_module", fake_import)

    ok, n = probe_cuda_mod.probe_cuda()
    assert (ok, n) == (False, 0)


# --------------------------------------------------------------------------- #
# Failure modes                                                               #
# --------------------------------------------------------------------------- #


def test_probe_cuda_import_error_returns_zero(monkeypatch):
    """ImportError on `ctranslate2` import (extras not installed) → (False, 0)."""
    from core.accel import probe_cuda as probe_cuda_mod

    real_import = importlib.import_module

    def fake_import(name: str, *args, **kwargs):
        if name == "ctranslate2":
            raise ImportError("No module named 'ctranslate2'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(probe_cuda_mod, "_register_cuda_dll_dirs", lambda: [])
    monkeypatch.setattr(probe_cuda_mod.importlib, "import_module", fake_import)

    ok, n = probe_cuda_mod.probe_cuda()
    assert (ok, n) == (False, 0)


def test_probe_cuda_oserror_on_import_returns_zero(monkeypatch):
    """OSError on import (DLL load failure: missing cuDNN/cublas) → (False, 0)."""
    from core.accel import probe_cuda as probe_cuda_mod

    real_import = importlib.import_module

    def fake_import(name: str, *args, **kwargs):
        if name == "ctranslate2":
            raise OSError(
                "[WinError 126] The specified module could not be found"
            )
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(probe_cuda_mod, "_register_cuda_dll_dirs", lambda: [])
    monkeypatch.setattr(probe_cuda_mod.importlib, "import_module", fake_import)

    ok, n = probe_cuda_mod.probe_cuda()
    assert (ok, n) == (False, 0)


def test_probe_cuda_oserror_at_runtime_returns_zero(monkeypatch):
    """OSError from `get_cuda_device_count()` (cuda runtime crash) → (False, 0)."""
    from core.accel import probe_cuda as probe_cuda_mod

    fake_ct2 = MagicMock()
    fake_ct2.get_cuda_device_count.side_effect = OSError("CUDA runtime error")

    real_import = importlib.import_module

    def fake_import(name: str, *args, **kwargs):
        if name == "ctranslate2":
            return fake_ct2
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(probe_cuda_mod, "_register_cuda_dll_dirs", lambda: [])
    monkeypatch.setattr(probe_cuda_mod.importlib, "import_module", fake_import)

    ok, n = probe_cuda_mod.probe_cuda()
    assert (ok, n) == (False, 0)


def test_probe_cuda_register_dll_dirs_still_called_even_on_import_failure(
    monkeypatch,
):
    """Defensive: even if ctranslate2 import fails, register_dll_dirs must have run.

    This prevents a future regression where someone re-orders the body to
    "try import first, register only on success" — that would re-introduce
    the C1 bug for the very next probe call on the same process.
    """
    from core.accel import probe_cuda as probe_cuda_mod

    register_called = {"n": 0}

    def fake_register() -> list[str]:
        register_called["n"] += 1
        return []

    real_import = importlib.import_module

    def fake_import(name: str, *args, **kwargs):
        if name == "ctranslate2":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(probe_cuda_mod, "_register_cuda_dll_dirs", fake_register)
    monkeypatch.setattr(probe_cuda_mod.importlib, "import_module", fake_import)

    probe_cuda_mod.probe_cuda()
    assert register_called["n"] == 1

import os
import sys
import pytest


def test_cuda_bin_dirs_added_to_path():
    if sys.platform != "win32":
        pytest.skip("win32-only CUDA DLL registration")
    from core.recording.transcriber import _register_cuda_dll_dirs
    added = _register_cuda_dll_dirs()
    if not added:
        pytest.skip("no nvidia CUDA packages installed")
    path = os.environ.get("PATH", "")
    for d in added:
        assert d in path, f"{d} not prepended to PATH"

"""Tests for `core.accel.cuda_dll._register_cuda_dll_dirs` (Sprint 1 / Task 1.1).

Contract:
  - Walks `site-packages/nvidia/*/bin` on Windows and calls
    `os.add_dll_directory` for every existing bin/ subdir.
  - Idempotent — calling twice does not call `os.add_dll_directory`
    a second time for an already-registered directory.
  - No-op on non-Windows (and silently when the nvidia wheel is missing).

All filesystem and subprocess boundaries are mocked — these tests never
actually invoke `os.add_dll_directory` against real CUDA wheels.
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_registered_dirs():
    """Clear the module-level idempotency cache before/after each test.

    The cache survives across tests because the `core.accel.cuda_dll` module
    is imported once per pytest process. Clearing here keeps each test
    self-contained.
    """
    from core.accel import cuda_dll
    cuda_dll._REGISTERED_DIRS.clear()
    yield
    cuda_dll._REGISTERED_DIRS.clear()


def _build_fake_nvidia_tree(root: Path, subpkgs: list[str]) -> Path:
    """Create `<root>/nvidia/<sub>/bin/` directories for each subpkg."""
    nvidia = root / "nvidia"
    for sub in subpkgs:
        (nvidia / sub / "bin").mkdir(parents=True, exist_ok=True)
    return nvidia


def _patch_find_spec(nvidia_dir: Path):
    fake_spec = SimpleNamespace(submodule_search_locations=[str(nvidia_dir)])
    return patch(
        "core.accel.cuda_dll.importlib.util.find_spec",
        return_value=fake_spec,
    )


def _force_windows(monkeypatch):
    """Make `_register_cuda_dll_dirs` take the Windows branch on any host."""
    from core.accel import cuda_dll
    monkeypatch.setattr(cuda_dll.sys, "platform", "win32")
    # `os.add_dll_directory` does not exist on non-Windows; install a stub so
    # the `hasattr` gate passes when the test host is Linux/macOS.
    if not hasattr(cuda_dll.os, "add_dll_directory"):
        monkeypatch.setattr(
            cuda_dll.os, "add_dll_directory", lambda d: None, raising=False
        )


# --------------------------------------------------------------------------- #
# Happy path                                                                  #
# --------------------------------------------------------------------------- #


def test_walks_nvidia_subdirs_and_calls_add_dll_directory_for_each(
    tmp_path, monkeypatch
):
    """Every `nvidia/<sub>/bin/` discovered must be passed to add_dll_directory."""
    from core.accel import cuda_dll

    _force_windows(monkeypatch)
    nvidia = _build_fake_nvidia_tree(
        tmp_path, ["cublas", "cudnn", "cuda_runtime", "cuda_nvrtc"]
    )
    add = MagicMock()
    monkeypatch.setattr(cuda_dll.os, "add_dll_directory", add)

    with _patch_find_spec(nvidia):
        result = cuda_dll._register_cuda_dll_dirs()

    expected = {
        str(nvidia / "cublas" / "bin"),
        str(nvidia / "cudnn" / "bin"),
        str(nvidia / "cuda_runtime" / "bin"),
        str(nvidia / "cuda_nvrtc" / "bin"),
    }
    actual_calls = {c.args[0] for c in add.call_args_list}
    assert actual_calls == expected, (
        f"add_dll_directory call set mismatch: got {actual_calls}, want {expected}"
    )
    assert add.call_count == len(expected)
    assert set(result) == expected


def test_subpackage_without_bin_dir_is_skipped(tmp_path, monkeypatch):
    """A nvidia/<sub>/ that lacks a bin/ subdir must NOT trigger a registration."""
    from core.accel import cuda_dll

    _force_windows(monkeypatch)
    nvidia = tmp_path / "nvidia"
    (nvidia / "cublas" / "bin").mkdir(parents=True)
    (nvidia / "weird_no_bin").mkdir(parents=True)  # no bin/ subdir

    add = MagicMock()
    monkeypatch.setattr(cuda_dll.os, "add_dll_directory", add)

    with _patch_find_spec(nvidia):
        result = cuda_dll._register_cuda_dll_dirs()

    assert result == [str(nvidia / "cublas" / "bin")]
    assert add.call_count == 1
    add.assert_called_once_with(str(nvidia / "cublas" / "bin"))


def test_prepends_added_dirs_to_path_env_var(tmp_path, monkeypatch):
    """PATH must be prepended with the newly-registered dirs so ctranslate2's
    transitive DLL resolver (which falls back to PATH) finds cublas/cuDNN."""
    from core.accel import cuda_dll

    _force_windows(monkeypatch)
    nvidia = _build_fake_nvidia_tree(tmp_path, ["cublas", "cudnn"])
    monkeypatch.setattr(cuda_dll.os, "add_dll_directory", MagicMock())
    monkeypatch.setenv("PATH", "C:\\preexisting")

    with _patch_find_spec(nvidia):
        cuda_dll._register_cuda_dll_dirs()

    path = os.environ["PATH"]
    assert str(nvidia / "cublas" / "bin") in path
    assert str(nvidia / "cudnn" / "bin") in path
    assert path.endswith("C:\\preexisting")


# --------------------------------------------------------------------------- #
# Idempotency                                                                 #
# --------------------------------------------------------------------------- #


def test_idempotent_second_call_does_not_re_register(tmp_path, monkeypatch):
    """Calling _register_cuda_dll_dirs() twice must not double-register dirs."""
    from core.accel import cuda_dll

    _force_windows(monkeypatch)
    nvidia = _build_fake_nvidia_tree(tmp_path, ["cublas", "cudnn"])
    add = MagicMock()
    monkeypatch.setattr(cuda_dll.os, "add_dll_directory", add)

    with _patch_find_spec(nvidia):
        first = cuda_dll._register_cuda_dll_dirs()
        second = cuda_dll._register_cuda_dll_dirs()

    assert sorted(first) == sorted(second), (
        "cumulative registered-dir list should be stable across calls"
    )
    assert len(first) == 2
    # Each unique dir registered exactly once across both calls.
    assert add.call_count == 2, (
        f"add_dll_directory called {add.call_count} times; expected 2 "
        "(once per unique dir, idempotent)"
    )


def test_idempotent_path_not_prepended_twice(tmp_path, monkeypatch):
    """PATH must NOT grow on a second no-op call."""
    from core.accel import cuda_dll

    _force_windows(monkeypatch)
    nvidia = _build_fake_nvidia_tree(tmp_path, ["cublas"])
    monkeypatch.setattr(cuda_dll.os, "add_dll_directory", MagicMock())
    monkeypatch.setenv("PATH", "C:\\preexisting")

    with _patch_find_spec(nvidia):
        cuda_dll._register_cuda_dll_dirs()
        path_after_first = os.environ["PATH"]
        cuda_dll._register_cuda_dll_dirs()
        path_after_second = os.environ["PATH"]

    assert path_after_first == path_after_second, (
        "PATH should be unchanged on idempotent re-call"
    )


# --------------------------------------------------------------------------- #
# No-op cases                                                                 #
# --------------------------------------------------------------------------- #


def test_noop_on_non_windows_returns_empty_and_does_not_probe(monkeypatch):
    """On Linux/macOS the function must short-circuit before touching anything."""
    from core.accel import cuda_dll

    monkeypatch.setattr(cuda_dll.sys, "platform", "linux")
    add = MagicMock()
    monkeypatch.setattr(cuda_dll.os, "add_dll_directory", add, raising=False)

    fake_spec = SimpleNamespace(submodule_search_locations=["/should/not/be/read"])
    with patch(
        "core.accel.cuda_dll.importlib.util.find_spec", return_value=fake_spec
    ) as fs:
        result = cuda_dll._register_cuda_dll_dirs()

    assert result == []
    add.assert_not_called()
    fs.assert_not_called(), "early-return must happen before find_spec lookup"


def test_noop_on_darwin(monkeypatch):
    """Same short-circuit on macOS."""
    from core.accel import cuda_dll

    monkeypatch.setattr(cuda_dll.sys, "platform", "darwin")
    add = MagicMock()
    monkeypatch.setattr(cuda_dll.os, "add_dll_directory", add, raising=False)

    result = cuda_dll._register_cuda_dll_dirs()

    assert result == []
    add.assert_not_called()


def test_noop_when_add_dll_directory_missing(monkeypatch):
    """If os.add_dll_directory is unavailable (e.g. ancient Python), no-op."""
    from core.accel import cuda_dll

    monkeypatch.setattr(cuda_dll.sys, "platform", "win32")
    monkeypatch.delattr(cuda_dll.os, "add_dll_directory", raising=False)

    result = cuda_dll._register_cuda_dll_dirs()
    assert result == []


def test_noop_when_nvidia_package_missing(monkeypatch):
    """If nvidia namespace package isn't importable, must return empty list."""
    from core.accel import cuda_dll

    _force_windows(monkeypatch)
    add = MagicMock()
    monkeypatch.setattr(cuda_dll.os, "add_dll_directory", add)

    with patch(
        "core.accel.cuda_dll.importlib.util.find_spec", return_value=None
    ):
        result = cuda_dll._register_cuda_dll_dirs()

    assert result == []
    add.assert_not_called()


def test_noop_when_find_spec_raises(monkeypatch):
    """If find_spec blows up (corrupt metadata, partial wheel), swallow + no-op."""
    from core.accel import cuda_dll

    _force_windows(monkeypatch)
    add = MagicMock()
    monkeypatch.setattr(cuda_dll.os, "add_dll_directory", add)

    with patch(
        "core.accel.cuda_dll.importlib.util.find_spec",
        side_effect=RuntimeError("metadata corrupted"),
    ):
        result = cuda_dll._register_cuda_dll_dirs()

    assert result == []
    add.assert_not_called()


def test_add_dll_directory_oserror_skips_dir_silently(tmp_path, monkeypatch):
    """A single dir failing with OSError must not abort the loop or be cached."""
    from core.accel import cuda_dll

    _force_windows(monkeypatch)
    nvidia = _build_fake_nvidia_tree(tmp_path, ["cublas", "cudnn"])

    cublas_bin = str(nvidia / "cublas" / "bin")
    cudnn_bin = str(nvidia / "cudnn" / "bin")

    def fake_add(d):
        if d == cublas_bin:
            raise OSError("simulated driver mismatch")

    monkeypatch.setattr(cuda_dll.os, "add_dll_directory", fake_add)

    with _patch_find_spec(nvidia):
        result = cuda_dll._register_cuda_dll_dirs()

    # Only the dir that succeeded ends up in the cumulative result.
    assert result == [cudnn_bin]
    assert cublas_bin not in cuda_dll._REGISTERED_DIRS
    assert cudnn_bin in cuda_dll._REGISTERED_DIRS

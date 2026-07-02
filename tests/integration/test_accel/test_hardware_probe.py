"""Integration tests for ``HardwareProbe.run()`` orchestrator.

Sprint 1 / Task 1.6 of `docs/superpowers/plans/2026-06-29-igpu-npu-acceleration.md`.

Coverage:

* ``test_run_returns_stub_profile_when_env_var_set``: with
  ``NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE=1`` the orchestrator returns
  ``_STUB_PROFILE`` without invoking any sub-probe.
* ``test_run_without_skip_calls_all_probes``: all 6 sub-probes are invoked
  exactly once and the resulting :class:`HwProfile` reflects the mocked
  return values (vendor / igpu / npu / ryzen_ai_gen derivation included).
* ``test_run_is_cached`` and ``test_clear_cache_forces_reprobe`` exercise
  the idempotency contract.
* ``test_pii_excluded`` parametrises over every ``HwProfile`` field and
  asserts no hostname / IP / MAC / serial / disk-path leaks through (the
  privacy guarantee documented in the dataclass docstring).

Sub-probes are mocked at the boundary (``patch("core.accel.probe.X")``);
no real ``pnputil`` / ``ctranslate2`` / ``nvidia-smi`` is invoked.
"""

from __future__ import annotations

import re
import socket
import threading
import uuid
from dataclasses import fields
from unittest.mock import patch

import pytest

from core.accel.probe import HardwareProbe
from core.accel.probe_env import ENV_VAR_NAME
from core.accel.profile import _STUB_PROFILE, HwProfile

# ----------------------------------------------------------------------------
# Mock helpers
# ----------------------------------------------------------------------------


# Sentinel that lets callers explicitly request ``dgpu=None`` (a CPU-only
# host) without being silently overridden by the default RTX 2080 Ti dict.
_UNSET = object()


def _patch_all_probes(
    *,
    cpu: str = "12th Gen Intel(R) Core(TM) i9-12900KF",
    cuda: tuple[bool, int] = (True, 1),
    dgpu: dict[str, object] | None = _UNSET,  # type: ignore[assignment]
    directml: bool = False,
    amd_npu: str | None = None,
    openvino_devices: tuple[str, ...] = (),
):
    """Apply ``patch`` to all 6 sub-probes at the ``core.accel.probe`` boundary.

    Returns a list of patcher objects so the caller can ``__enter__`` them
    via ``contextlib.ExitStack`` if needed. For the common case, callers
    just use ``with _patch_all_probes(...) as patches: ...``.

    ``dgpu`` uses the ``_UNSET`` sentinel so an explicit ``dgpu=None``
    (CPU-only / Intel-only / AMD-only host) is honoured rather than being
    replaced by the default RTX 2080 Ti dict.
    """
    if dgpu is _UNSET:
        dgpu = {"name": "NVIDIA GeForce RTX 2080 Ti", "vram_mb": 11264}
    return [
        patch("core.accel.probe.probe_cpu", return_value=cpu),
        patch("core.accel.probe.probe_cuda", return_value=cuda),
        patch("core.accel.probe.probe_dgpu", return_value=dgpu),
        patch("core.accel.probe.probe_directml", return_value=directml),
        patch("core.accel.probe.probe_amd_npu", return_value=amd_npu),
        patch("core.accel.probe.probe_openvino_devices", return_value=openvino_devices),
    ]


class _MockedProbes:
    """Tiny context manager that enters every patcher returned by
    :func:`_patch_all_probes` and exposes the resulting mock objects.

    Saves boilerplate vs ``ExitStack`` for the common "set all 6, assert
    call counts on a couple" pattern.
    """

    def __init__(self, **kwargs):
        self._patchers = _patch_all_probes(**kwargs)
        self.mocks: dict[str, object] = {}

    def __enter__(self):
        for p in self._patchers:
            m = p.start()
            # The patch target attribute is the last dotted segment.
            self.mocks[p.attribute] = m
        return self.mocks

    def __exit__(self, exc_type, exc, tb):
        for p in reversed(self._patchers):
            p.stop()


# ----------------------------------------------------------------------------
# Env-var short-circuit
# ----------------------------------------------------------------------------


class TestSkipEnvVar:
    def test_run_returns_stub_profile_when_env_var_set(self, monkeypatch):
        """With ``NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE=1``, ``_STUB_PROFILE`` is returned."""
        monkeypatch.setenv(ENV_VAR_NAME, "1")
        with _MockedProbes() as mocks:
            profile = HardwareProbe().run()
        assert profile is _STUB_PROFILE
        # Critical: NO sub-probe must have fired (cost / isolation invariant).
        for name, mock in mocks.items():
            assert mock.call_count == 0, f"{name} fired despite skip env var"

    def test_run_with_env_unset_invokes_probes(self, monkeypatch):
        """Defensive negative: clearing the env var lets the real assembly run."""
        monkeypatch.delenv(ENV_VAR_NAME, raising=False)
        with _MockedProbes(cuda=(False, 0), dgpu=None) as mocks:
            HardwareProbe().run()
        for name, mock in mocks.items():
            assert mock.call_count == 1, f"{name} not invoked (count={mock.call_count})"


# ----------------------------------------------------------------------------
# Full-probe assembly
# ----------------------------------------------------------------------------


class TestRunAssemblesProfile:
    def test_nvidia_cuda_box(self, monkeypatch):
        """RTX 2080 Ti dev box — vendor=nvidia, has_cuda=True, openvino_devices=()."""
        monkeypatch.delenv(ENV_VAR_NAME, raising=False)
        with _MockedProbes(
            cpu="12th Gen Intel(R) Core(TM) i9-12900KF",
            cuda=(True, 1),
            dgpu={"name": "NVIDIA GeForce RTX 2080 Ti", "vram_mb": 11264},
            directml=False,
            amd_npu=None,
            openvino_devices=(),
        ):
            profile = HardwareProbe().run()

        assert isinstance(profile, HwProfile)
        assert profile.vendor == "nvidia"
        assert profile.cpu_brand == "12th Gen Intel(R) Core(TM) i9-12900KF"
        assert profile.has_cuda is True
        assert profile.cuda_device_count == 1
        assert profile.dgpu == "NVIDIA GeForce RTX 2080 Ti"
        assert profile.vram_mb == 11264
        assert profile.igpu is None
        assert profile.npu is None
        assert profile.ryzen_ai_gen is None
        assert profile.openvino_devices == ()
        assert profile.has_directml is False

    def test_intel_core_ultra_with_igpu_and_npu(self, monkeypatch):
        """Meteor / Lunar / Arrow Lake — vendor=intel, igpu + npu populated."""
        monkeypatch.delenv(ENV_VAR_NAME, raising=False)
        with _MockedProbes(
            cpu="Intel(R) Core(TM) Ultra 7 155H",
            cuda=(False, 0),
            dgpu=None,
            directml=True,
            amd_npu=None,
            openvino_devices=("CPU", "GPU", "NPU"),
        ):
            profile = HardwareProbe().run()

        assert profile.vendor == "intel"
        assert profile.cpu_brand == "Intel(R) Core(TM) Ultra 7 155H"
        assert profile.has_cuda is False
        assert profile.cuda_device_count == 0
        assert profile.dgpu is None
        assert profile.vram_mb is None
        assert profile.igpu == "Intel iGPU"
        assert profile.npu == "Intel NPU"
        assert profile.ryzen_ai_gen is None
        assert profile.openvino_devices == ("CPU", "GPU", "NPU")
        assert profile.has_directml is True

    @pytest.mark.parametrize(
        "chip,expected_gen",
        [
            ("phoenix", 1),
            ("hawk_point", 1),
            ("strix", 2),
            ("krackan_point", 2),
        ],
    )
    def test_amd_ryzen_ai_chip_families(self, monkeypatch, chip, expected_gen):
        """All 4 AMD chip families map to vendor=amd + correct ryzen_ai_gen."""
        monkeypatch.delenv(ENV_VAR_NAME, raising=False)
        with _MockedProbes(
            cpu="AMD Ryzen AI 9 365",
            cuda=(False, 0),
            dgpu=None,
            directml=True,
            amd_npu=chip,
            openvino_devices=(),
        ):
            profile = HardwareProbe().run()

        assert profile.vendor == "amd"
        assert profile.npu == chip
        assert profile.ryzen_ai_gen == expected_gen
        assert profile.has_directml is True

    def test_intel_npu_priority_over_amd_when_both_present(self, monkeypatch):
        """Defensive: if both openvino-NPU and an AMD chip surface, Intel label wins.

        This is the same priority spec §6.3 enforces ('single NPU consumer')
        and matches the Planner's tie-break in Sprint 2.
        """
        monkeypatch.delenv(ENV_VAR_NAME, raising=False)
        with _MockedProbes(
            cpu="weird hybrid",
            cuda=(False, 0),
            dgpu=None,
            directml=True,
            amd_npu="strix",
            openvino_devices=("CPU", "GPU", "NPU"),
        ):
            profile = HardwareProbe().run()
        assert profile.npu == "Intel NPU"
        # vendor is still amd (priority: cuda > amd-npu > intel-openvino).
        assert profile.vendor == "amd"

    def test_no_acceleration_returns_unknown_vendor(self, monkeypatch):
        """Bare CPU-only VM — all accelerator fields None / False / 0."""
        monkeypatch.delenv(ENV_VAR_NAME, raising=False)
        with _MockedProbes(
            cpu="QEMU Virtual CPU",
            cuda=(False, 0),
            dgpu=None,
            directml=False,
            amd_npu=None,
            openvino_devices=(),
        ):
            profile = HardwareProbe().run()
        assert profile.vendor == "unknown"
        assert profile.dgpu is None
        assert profile.igpu is None
        assert profile.npu is None
        assert profile.has_cuda is False
        assert profile.has_directml is False

    def test_all_six_probes_called_exactly_once(self, monkeypatch):
        """Wire-up smoke: every documented sub-probe is invoked, none twice."""
        monkeypatch.delenv(ENV_VAR_NAME, raising=False)
        with _MockedProbes() as mocks:
            HardwareProbe().run()
        expected = {
            "probe_cpu",
            "probe_cuda",
            "probe_dgpu",
            "probe_directml",
            "probe_amd_npu",
            "probe_openvino_devices",
        }
        assert set(mocks) == expected
        for name, mock in mocks.items():
            assert mock.call_count == 1, f"{name} called {mock.call_count}x (want 1)"


# ----------------------------------------------------------------------------
# Caching / idempotency
# ----------------------------------------------------------------------------


class TestCaching:
    def test_run_is_cached(self, monkeypatch):
        """Second ``run()`` returns the same object reference without re-probing."""
        monkeypatch.delenv(ENV_VAR_NAME, raising=False)
        probe = HardwareProbe()
        with _MockedProbes() as mocks:
            first = probe.run()
            second = probe.run()
        assert first is second, "cached profile must be identity-equal"
        for name, mock in mocks.items():
            assert mock.call_count == 1, (
                f"{name} re-invoked on cached call (count={mock.call_count})"
            )

    def test_clear_cache_forces_reprobe(self, monkeypatch):
        """After ``clear_cache()`` the probes fire again on next ``run()``."""
        monkeypatch.delenv(ENV_VAR_NAME, raising=False)
        probe = HardwareProbe()
        with _MockedProbes() as mocks:
            probe.run()
            probe.clear_cache()
            probe.run()
        for name, mock in mocks.items():
            assert mock.call_count == 2, (
                f"{name} not re-invoked after clear_cache (count={mock.call_count})"
            )

    def test_clear_cache_with_no_cached_value_is_noop(self, monkeypatch):
        """``clear_cache()`` before the first ``run()`` must not crash."""
        monkeypatch.delenv(ENV_VAR_NAME, raising=False)
        probe = HardwareProbe()
        probe.clear_cache()  # no-op; should not raise.
        with _MockedProbes() as mocks:
            probe.run()
        for mock in mocks.values():
            assert mock.call_count == 1

    def test_stub_profile_is_not_cached(self, monkeypatch):
        """Toggling the skip env between calls must take effect on the next run.

        Stub mode is intentionally not cached so that integration fixtures
        which flip ``NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE`` around a single
        test do not leak stub state into later tests using the same probe.
        """
        probe = HardwareProbe()
        monkeypatch.setenv(ENV_VAR_NAME, "1")
        first = probe.run()
        assert first is _STUB_PROFILE

        monkeypatch.delenv(ENV_VAR_NAME, raising=False)
        with _MockedProbes(cuda=(True, 1)) as mocks:
            second = probe.run()
        assert second is not _STUB_PROFILE
        assert second.has_cuda is True
        # Probes must have actually fired (not served from a stale cache).
        for mock in mocks.values():
            assert mock.call_count == 1

    def test_run_is_thread_safe(self, monkeypatch):
        """Concurrent ``run()`` calls must not invoke probes more than once."""
        monkeypatch.delenv(ENV_VAR_NAME, raising=False)
        probe = HardwareProbe()
        N = 16
        results: list[HwProfile] = []
        barrier = threading.Barrier(N)

        def worker():
            barrier.wait()
            results.append(probe.run())

        with _MockedProbes() as mocks:
            threads = [threading.Thread(target=worker) for _ in range(N)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        # Every worker saw the same cached object.
        assert all(r is results[0] for r in results)
        # And the underlying probes ran exactly once across all threads.
        for name, mock in mocks.items():
            assert mock.call_count == 1, (
                f"{name} called {mock.call_count}x under thread contention"
            )


# ----------------------------------------------------------------------------
# PII / privacy invariant
# ----------------------------------------------------------------------------


# Patterns that MUST NOT appear in any HwProfile field's string representation.
# Disk-path patterns cover the typical "site-packages/nvidia/..." leak that
# would happen if probe_cuda accidentally returned a DLL search path.
_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ipv4", re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")),
    ("ipv6", re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{1,4}\b")),
    ("mac", re.compile(r"\b[0-9a-fA-F]{2}(?:[:-][0-9a-fA-F]{2}){5}\b")),
    # Windows-style absolute path: drive letter + colon + backslash.
    ("windows_path", re.compile(r"[A-Za-z]:\\")),
    # POSIX-style absolute path starting with /home, /Users, /root, /var, /tmp.
    (
        "posix_path",
        re.compile(r"(?<![A-Za-z0-9])/(?:home|Users|root|var|tmp|mnt|opt)/"),
    ),
    # UUID (covers Windows machine GUID / drive serial-style leaks).
    (
        "uuid",
        re.compile(
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
        ),
    ),
)


@pytest.fixture
def assembled_profile(monkeypatch):
    """A representative real-world :class:`HwProfile` (dev-box-shaped values).

    The CPU brand intentionally includes punctuation so the patterns get a
    realistic substring to scan, not just the trivial ``"test"`` stub.
    """
    monkeypatch.delenv(ENV_VAR_NAME, raising=False)
    with _MockedProbes(
        cpu="12th Gen Intel(R) Core(TM) i9-12900KF",
        cuda=(True, 1),
        dgpu={"name": "NVIDIA GeForce RTX 2080 Ti", "vram_mb": 11264},
        directml=False,
        amd_npu=None,
        openvino_devices=(),
    ):
        return HardwareProbe().run()


@pytest.mark.parametrize("field", [f.name for f in fields(HwProfile)])
def test_pii_excluded(field, assembled_profile):
    """No HwProfile field's string repr may contain hostname / IP / MAC / etc.

    Parametrising over every field name guarantees that any future addition
    to :class:`HwProfile` is automatically swept by this gate.
    """
    value = getattr(assembled_profile, field)
    if value is None:
        return
    rendered = str(value)

    hostname = socket.gethostname()
    if hostname:
        assert hostname not in rendered, f"hostname leak in {field}={rendered!r}"

    # Stable machine-wide identifier candidate — uuid.getnode returns the MAC
    # (or a random integer fallback). Either way it must not appear verbatim.
    mac_int = uuid.getnode()
    mac_hex = f"{mac_int:012x}"
    assert mac_hex not in rendered.lower(), (
        f"MAC-as-int leak in {field}={rendered!r}"
    )

    for name, pattern in _PII_PATTERNS:
        match = pattern.search(rendered)
        assert match is None, (
            f"PII pattern {name!r} matched in {field}={rendered!r}: "
            f"{match.group(0) if match else ''}"
        )


def test_pii_test_also_covers_stub_profile():
    """The stub profile is also a HwProfile — it must pass the same gate."""
    hostname = socket.gethostname()
    for f in fields(HwProfile):
        value = getattr(_STUB_PROFILE, f.name)
        if value is None:
            continue
        rendered = str(value)
        if hostname:
            assert hostname not in rendered
        for _, pattern in _PII_PATTERNS:
            assert pattern.search(rendered) is None

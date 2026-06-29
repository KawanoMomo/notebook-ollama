"""Unit tests for the 4 individual hardware probes used by HardwareProbe.

Sprint 1 / Task 1.4 of docs/superpowers/plans/2026-06-29-igpu-npu-acceleration.md.

All probes MUST:
- Mock subprocess + winreg in tests (no real shell-outs).
- Time out at <=5 seconds in production code.
- Return None / empty gracefully on any failure (no exception escapes).
- NOT include hostname / IP / MAC / serial in output (privacy guarantee).
"""

from __future__ import annotations

import socket
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from core.accel.probe import probe_amd_npu, probe_cpu, probe_dgpu, probe_directml

# -----------------------------------------------------------------------------
# probe_cpu
# -----------------------------------------------------------------------------


class TestProbeCpu:
    def test_returns_winreg_processor_name_on_win32(self):
        fake_winreg = MagicMock()
        fake_key = MagicMock()
        fake_winreg.OpenKey.return_value = fake_key
        fake_winreg.QueryValueEx.return_value = (
            "12th Gen Intel(R) Core(TM) i9-12900KF",
            1,
        )
        fake_winreg.HKEY_LOCAL_MACHINE = 0
        with (
            patch("core.accel.probe.sys.platform", "win32"),
            patch.dict("sys.modules", {"winreg": fake_winreg}),
        ):
            brand = probe_cpu()
        assert brand == "12th Gen Intel(R) Core(TM) i9-12900KF"

    def test_winreg_failure_falls_back_to_platform_processor(self):
        fake_winreg = MagicMock()
        fake_winreg.OpenKey.side_effect = OSError("registry not found")
        fake_winreg.HKEY_LOCAL_MACHINE = 0
        with (
            patch("core.accel.probe.sys.platform", "win32"),
            patch.dict("sys.modules", {"winreg": fake_winreg}),
            patch("core.accel.probe.platform.processor", return_value="AMD64 Family 23"),
        ):
            brand = probe_cpu()
        assert brand == "AMD64 Family 23"

    def test_non_windows_uses_platform_processor(self):
        with (
            patch("core.accel.probe.sys.platform", "linux"),
            patch("core.accel.probe.platform.processor", return_value="x86_64"),
        ):
            assert probe_cpu() == "x86_64"

    def test_empty_platform_processor_returns_unknown_sentinel(self):
        with (
            patch("core.accel.probe.sys.platform", "linux"),
            patch("core.accel.probe.platform.processor", return_value=""),
        ):
            assert probe_cpu() == "unknown"

    def test_all_exceptions_swallowed_returns_unknown(self):
        with (
            patch("core.accel.probe.sys.platform", "linux"),
            patch(
                "core.accel.probe.platform.processor",
                side_effect=RuntimeError("boom"),
            ),
        ):
            assert probe_cpu() == "unknown"

    def test_never_includes_hostname(self):
        """Privacy guarantee: probe_cpu() must never leak the machine hostname."""
        hostname = socket.gethostname()
        with (
            patch("core.accel.probe.sys.platform", "linux"),
            patch("core.accel.probe.platform.processor", return_value="x86_64"),
        ):
            brand = probe_cpu()
        assert hostname not in brand


# -----------------------------------------------------------------------------
# probe_dgpu (nvidia-smi only)
# -----------------------------------------------------------------------------


def _completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["nvidia-smi"], returncode=returncode, stdout=stdout, stderr=""
    )


class TestProbeDgpu:
    def test_happy_path_parses_name_and_vram_mb(self):
        with patch(
            "core.accel.probe.subprocess.run",
            return_value=_completed("NVIDIA GeForce RTX 2080 Ti, 11264\n"),
        ):
            info = probe_dgpu()
        assert info == {"name": "NVIDIA GeForce RTX 2080 Ti", "vram_mb": 11264}

    def test_first_gpu_used_when_multiple_present(self):
        out = "NVIDIA GeForce RTX 2080 Ti, 11264\nNVIDIA GeForce GTX 1080, 8192\n"
        with patch(
            "core.accel.probe.subprocess.run", return_value=_completed(out)
        ):
            info = probe_dgpu()
        assert info == {"name": "NVIDIA GeForce RTX 2080 Ti", "vram_mb": 11264}

    def test_missing_binary_returns_none(self):
        with patch(
            "core.accel.probe.subprocess.run",
            side_effect=FileNotFoundError("nvidia-smi not found"),
        ):
            assert probe_dgpu() is None

    def test_nonzero_exit_returns_none(self):
        with patch(
            "core.accel.probe.subprocess.run",
            return_value=_completed("", returncode=9),
        ):
            assert probe_dgpu() is None

    def test_malformed_output_returns_none(self):
        with patch(
            "core.accel.probe.subprocess.run",
            return_value=_completed("garbage-line-no-comma"),
        ):
            assert probe_dgpu() is None

    def test_empty_output_returns_none(self):
        with patch(
            "core.accel.probe.subprocess.run",
            return_value=_completed("\n   \n"),
        ):
            assert probe_dgpu() is None

    def test_timeout_returns_none(self):
        with patch(
            "core.accel.probe.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=5),
        ):
            assert probe_dgpu() is None

    def test_uses_timeout_at_most_5_seconds(self):
        captured: dict[str, object] = {}

        def fake_run(*args, **kwargs):
            captured["timeout"] = kwargs.get("timeout")
            return _completed("NVIDIA GeForce RTX 2080 Ti, 11264")

        with patch("core.accel.probe.subprocess.run", side_effect=fake_run):
            probe_dgpu()
        assert isinstance(captured["timeout"], (int, float))
        assert captured["timeout"] <= 5

    def test_unexpected_exception_returns_none(self):
        with patch(
            "core.accel.probe.subprocess.run",
            side_effect=RuntimeError("subprocess exploded"),
        ):
            assert probe_dgpu() is None

    def test_no_hostname_in_result(self):
        hostname = socket.gethostname()
        with patch(
            "core.accel.probe.subprocess.run",
            return_value=_completed("NVIDIA GeForce RTX 2080 Ti, 11264"),
        ):
            info = probe_dgpu()
        assert info is not None
        assert hostname not in info["name"]


# -----------------------------------------------------------------------------
# probe_directml
# -----------------------------------------------------------------------------


class TestProbeDirectml:
    def test_returns_true_when_dml_provider_available(self):
        fake_ort = MagicMock()
        fake_ort.get_available_providers.return_value = [
            "DmlExecutionProvider",
            "CPUExecutionProvider",
        ]
        with (
            patch("core.accel.probe.sys.platform", "win32"),
            patch.dict("sys.modules", {"onnxruntime": fake_ort}),
        ):
            assert probe_directml() is True

    def test_returns_false_when_provider_missing(self):
        fake_ort = MagicMock()
        fake_ort.get_available_providers.return_value = ["CPUExecutionProvider"]
        with (
            patch("core.accel.probe.sys.platform", "win32"),
            patch.dict("sys.modules", {"onnxruntime": fake_ort}),
        ):
            assert probe_directml() is False

    def test_returns_false_when_module_missing(self):
        with (
            patch("core.accel.probe.sys.platform", "win32"),
            patch.dict("sys.modules", {"onnxruntime": None}),
        ):
            assert probe_directml() is False

    def test_returns_false_on_non_windows(self):
        with patch("core.accel.probe.sys.platform", "linux"):
            assert probe_directml() is False

    def test_returns_false_when_get_providers_raises(self):
        fake_ort = MagicMock()
        fake_ort.get_available_providers.side_effect = RuntimeError("boom")
        with (
            patch("core.accel.probe.sys.platform", "win32"),
            patch.dict("sys.modules", {"onnxruntime": fake_ort}),
        ):
            assert probe_directml() is False


# -----------------------------------------------------------------------------
# probe_amd_npu — pnputil /enum-devices /bus PCI /deviceids parsing
# -----------------------------------------------------------------------------


# Real-shape pnputil output fragments per spec §2.
PNPUTIL_PHOENIX = (
    "Microsoft PnP Utility\r\n"
    "\r\n"
    "Instance ID:    PCI\\VEN_1022&DEV_1502&SUBSYS_00000000&REV_00\\3&11583659&0&D8\r\n"
    "Device Description: AMD IPU Device\r\n"
)
PNPUTIL_HAWK_POINT = (
    # Hawk Point shares DEV_1502 with Phoenix; CPU brand disambiguates.
    "Instance ID:    PCI\\VEN_1022&DEV_1502&SUBSYS_00000000&REV_00\\3&11583659&0&D8\r\n"
    "Device Description: AMD IPU Device\r\n"
)
PNPUTIL_STRIX = (
    "Instance ID:    PCI\\VEN_1022&DEV_17F0&SUBSYS_00000000&REV_10\\3&11583659&0&D8\r\n"
    "Device Description: AMD NPU Device\r\n"
)
PNPUTIL_STRIX_REV_00 = (
    "Instance ID:    PCI\\VEN_1022&DEV_17F0&SUBSYS_00000000&REV_00\\3&11583659&0&D8\r\n"
)
PNPUTIL_STRIX_REV_11 = (
    "Instance ID:    PCI\\VEN_1022&DEV_17F0&SUBSYS_00000000&REV_11\\3&11583659&0&D8\r\n"
)
PNPUTIL_KRACKAN = (
    "Instance ID:    PCI\\VEN_1022&DEV_17F0&SUBSYS_00000000&REV_20\\3&11583659&0&D8\r\n"
    "Device Description: AMD NPU Device\r\n"
)
PNPUTIL_NO_NPU = (
    "Instance ID:    PCI\\VEN_1022&DEV_1638&SUBSYS_00000000&REV_00\\3&11583659&0&D8\r\n"
    "Device Description: AMD GPU\r\n"
)


class TestProbeAmdNpu:
    @pytest.mark.parametrize(
        "fragment,cpu_brand,expected",
        [
            (PNPUTIL_PHOENIX, "AMD Ryzen 7 7840U", "phoenix"),
            (PNPUTIL_PHOENIX, None, "phoenix"),  # Default for DEV_1502
            (PNPUTIL_HAWK_POINT, "AMD Ryzen 7 8840U", "hawk_point"),
            (PNPUTIL_STRIX, "AMD Ryzen AI 9 365", "strix"),
            (PNPUTIL_STRIX_REV_00, None, "strix"),
            (PNPUTIL_STRIX_REV_11, None, "strix"),
            (PNPUTIL_KRACKAN, "AMD Ryzen AI 7 350", "krackan_point"),
            (PNPUTIL_NO_NPU, None, None),
            ("", None, None),
        ],
    )
    def test_chip_family_detection(self, fragment, cpu_brand, expected):
        with (
            patch("core.accel.probe.sys.platform", "win32"),
            patch(
                "core.accel.probe.subprocess.run",
                return_value=_completed(fragment),
            ),
        ):
            assert probe_amd_npu(cpu_brand=cpu_brand) == expected

    def test_non_windows_returns_none(self):
        with patch("core.accel.probe.sys.platform", "linux"):
            assert probe_amd_npu() is None

    def test_missing_binary_returns_none(self):
        with (
            patch("core.accel.probe.sys.platform", "win32"),
            patch(
                "core.accel.probe.subprocess.run",
                side_effect=FileNotFoundError("pnputil not found"),
            ),
        ):
            assert probe_amd_npu() is None

    def test_nonzero_exit_returns_none(self):
        with (
            patch("core.accel.probe.sys.platform", "win32"),
            patch(
                "core.accel.probe.subprocess.run",
                return_value=_completed("", returncode=1),
            ),
        ):
            assert probe_amd_npu() is None

    def test_malformed_output_returns_none(self):
        with (
            patch("core.accel.probe.sys.platform", "win32"),
            patch(
                "core.accel.probe.subprocess.run",
                return_value=_completed("totally unrelated text\nVEN_8086&DEV_1234"),
            ),
        ):
            assert probe_amd_npu() is None

    def test_timeout_returns_none(self):
        with (
            patch("core.accel.probe.sys.platform", "win32"),
            patch(
                "core.accel.probe.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="pnputil", timeout=5),
            ),
        ):
            assert probe_amd_npu() is None

    def test_uses_timeout_at_most_5_seconds(self):
        captured: dict[str, object] = {}

        def fake_run(*args, **kwargs):
            captured["timeout"] = kwargs.get("timeout")
            return _completed(PNPUTIL_PHOENIX)

        with (
            patch("core.accel.probe.sys.platform", "win32"),
            patch("core.accel.probe.subprocess.run", side_effect=fake_run),
        ):
            probe_amd_npu()
        assert isinstance(captured["timeout"], (int, float))
        assert captured["timeout"] <= 5

    def test_unexpected_exception_returns_none(self):
        with (
            patch("core.accel.probe.sys.platform", "win32"),
            patch(
                "core.accel.probe.subprocess.run",
                side_effect=RuntimeError("subprocess exploded"),
            ),
        ):
            assert probe_amd_npu() is None

    def test_unknown_rev_falls_back_to_strix_family(self):
        """DEV_17F0 with an unknown REV is still XDNA2; default to 'strix'."""
        fragment = (
            "Instance ID:    PCI\\VEN_1022&DEV_17F0&SUBSYS_X&REV_FF\\X\r\n"
        )
        with (
            patch("core.accel.probe.sys.platform", "win32"),
            patch(
                "core.accel.probe.subprocess.run",
                return_value=_completed(fragment),
            ),
        ):
            assert probe_amd_npu() == "strix"


# -----------------------------------------------------------------------------
# Cross-cutting: privacy invariant for all probes (no hostname leakage)
# -----------------------------------------------------------------------------


def test_all_probes_never_leak_hostname():
    """Privacy guarantee across the 4 probes."""
    hostname = socket.gethostname()
    if not hostname:
        pytest.skip("no hostname configured")

    with (
        patch("core.accel.probe.sys.platform", "win32"),
        patch("core.accel.probe.platform.processor", return_value="x86_64"),
        patch(
            "core.accel.probe.subprocess.run",
            return_value=_completed("NVIDIA GeForce RTX 2080 Ti, 11264"),
        ),
        patch.dict(
            "sys.modules",
            {"onnxruntime": None, "winreg": None},
        ),
    ):
        cpu = probe_cpu()
        dgpu = probe_dgpu()
        directml = probe_directml()
        amd_npu = probe_amd_npu()

    for value in (cpu, str(dgpu), str(directml), str(amd_npu)):
        assert hostname not in value, f"hostname leak in {value!r}"

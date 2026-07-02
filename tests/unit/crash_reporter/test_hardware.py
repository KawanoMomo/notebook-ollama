"""Task 1.3 — `core/crash_reporter/hardware.py` のテスト。

spec §6.2 準拠: ハードウェア情報は採取するが、PII (hostname / IP /
MAC / ディスクパス) は含めない。psutil / nvidia-smi が無い環境では
"<unavailable>" にフォールバックする。

NOTE (adversarial-review 2026-06-28): 旧テストは 4 列の
`name, vram, cuda, driver` を mock していたが、`_run_nvidia_smi` が
発行する `--query-gpu=name,memory.total,driver_version` は実環境では
3 列しか返さない (CUDA Version はクエリ対象に含まれていない)。
よって本テストは 3 列の実シェイプのみを検証し、`cuda_version`
キーは contract から削除した。(spec §6.2 更新済み)
"""
from __future__ import annotations

from unittest.mock import patch

from core.crash_reporter import hardware


def test_collect_returns_required_keys():
    result = hardware.collect()
    required = {
        "cpu_model", "cpu_cores", "cpu_threads",
        "ram_total_gb", "ram_available_gb",
        "gpu_model", "gpu_vram_mb", "driver_version",
        "os_arch", "os_platform", "python_version", "disk_free_gb",
    }
    assert required <= set(result.keys())


def test_collect_does_not_expose_cuda_version_key():
    """contract (option b): cuda_version は採取コマンドが返さないので key 自体出さない。"""
    result = hardware.collect()
    assert "cuda_version" not in result


def test_collect_does_not_leak_hostname():
    result = hardware.collect()
    import platform
    host = platform.node()
    for v in result.values():
        if isinstance(v, str):
            assert host == "" or host not in v, (
                f"hostname leaked into hardware.collect(): {v!r}"
            )


def test_collect_handles_nvidia_smi_missing():
    with patch("core.crash_reporter.hardware._run_nvidia_smi", return_value=None):
        r = hardware.collect()
    assert r["gpu_model"] == "<unavailable>"
    assert r["gpu_vram_mb"] == "<unavailable>"
    assert r["driver_version"] == "<unavailable>"


def test_collect_handles_psutil_missing(monkeypatch):
    monkeypatch.setattr(hardware, "_psutil", None)
    r = hardware.collect()
    assert r["ram_total_gb"] == "<unavailable>"
    assert r["ram_available_gb"] == "<unavailable>"
    assert r["disk_free_gb"] == "<unavailable>"


def test_collect_parses_nvidia_smi_csv_three_columns():
    """`_run_nvidia_smi` の実シェイプ (3 列: name, memory.total, driver_version) を検証。"""
    fake = "NVIDIA GeForce RTX 2080 Ti, 11264, 555.42\n"
    with patch("core.crash_reporter.hardware._run_nvidia_smi", return_value=fake):
        r = hardware.collect()
    assert r["gpu_model"] == "NVIDIA GeForce RTX 2080 Ti"
    assert r["gpu_vram_mb"] == 11264
    assert r["driver_version"] == "555.42"


def test_collect_handles_empty_nvidia_smi_output():
    """nvidia-smi が呼べたが空文字列を返した場合 (権限など) のフォールバック。"""
    with patch("core.crash_reporter.hardware._run_nvidia_smi", return_value=""):
        r = hardware.collect()
    assert r["gpu_model"] == "<unavailable>"
    assert r["gpu_vram_mb"] == "<unavailable>"
    assert r["driver_version"] == "<unavailable>"


def test_collect_handles_one_column_nvidia_smi_output():
    """カラム数不足 (1 列のみ) は全フィールド unavailable にフォールバック。"""
    fake = "NVIDIA GeForce RTX 2080 Ti\n"
    with patch("core.crash_reporter.hardware._run_nvidia_smi", return_value=fake):
        r = hardware.collect()
    assert r["gpu_model"] == "<unavailable>"
    assert r["gpu_vram_mb"] == "<unavailable>"
    assert r["driver_version"] == "<unavailable>"


def test_collect_handles_two_column_nvidia_smi_output():
    """カラム数不足 (2 列) は全フィールド unavailable にフォールバック。"""
    fake = "NVIDIA GeForce RTX 2080 Ti, 11264\n"
    with patch("core.crash_reporter.hardware._run_nvidia_smi", return_value=fake):
        r = hardware.collect()
    assert r["gpu_model"] == "<unavailable>"
    assert r["gpu_vram_mb"] == "<unavailable>"
    assert r["driver_version"] == "<unavailable>"


def test_collect_handles_non_integer_vram():
    """memory.total が parse 不能なときは数値フィールドのみ unavailable。"""
    fake = "NVIDIA GeForce RTX 2080 Ti, N/A, 555.42\n"
    with patch("core.crash_reporter.hardware._run_nvidia_smi", return_value=fake):
        r = hardware.collect()
    assert r["gpu_model"] == "NVIDIA GeForce RTX 2080 Ti"
    assert r["gpu_vram_mb"] == "<unavailable>"
    assert r["driver_version"] == "555.42"

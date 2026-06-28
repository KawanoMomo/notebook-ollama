"""ハードウェア / 実行環境のスナップショット採取 (PII を含めない)。

spec §6.2 「個人特定可能なハードウェア情報も除外」: hostname / MAC / IP /
ディスクパス / シリアル番号は含めない。psutil / nvidia-smi が無い環境では
該当値を "<unavailable>" にしてフォールバックする。

NOTE (adversarial-review 2026-06-28): 旧実装は `_parse_nvidia_smi` 内で
4 列 (name, vram, cuda, driver) と 3 列の両方を許容していたが、
`_run_nvidia_smi` の `--query-gpu=name,memory.total,driver_version`
クエリは CUDA Version を要求していないため、4 列の出力は実環境では
発生しない。`cuda_version` フィールドは contract から削除した
(option b in adversarial review)。CUDA バージョンが必要になった場合は
`nvidia-smi` (引数なし) の header line を best-effort で別途パースする。
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

try:
    import psutil as _psutil  # type: ignore
except ImportError:  # pragma: no cover - environment dependent
    _psutil = None

_UNAVAIL = "<unavailable>"


def _run_nvidia_smi() -> str | None:
    """`nvidia-smi` を呼び CSV 1 行を返す。未インストールやエラーなら None。

    spec §6.2: GPU 情報は採取するが、出力からシリアル番号などの個人特定情報を
    避けるため `name,memory.total,driver_version` のみ。
    """
    # PATH 経由で nvidia-smi を呼ぶのは意図的 (各環境で異なる場所にインストールされる)
    cmd = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,driver_version",
        "--format=csv,noheader,nounits",
    ]
    try:
        out = subprocess.run(  # noqa: S603 - 引数は固定リテラルでユーザー入力なし
            cmd,
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        return out.stdout
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return None


def _parse_nvidia_smi(text: str | None) -> dict[str, str | int]:
    """`nvidia-smi` の CSV 出力を dict に変換する。

    - 3 列 (name, memory.total, driver_version) のみを許容
      (`_run_nvidia_smi` が発行するクエリと一致)。
    - 解析失敗時は全フィールド "<unavailable>"。
    - `cuda_version` は contract から除外済み (この関数は返さない)。
    """
    unavailable: dict[str, str | int] = {
        "gpu_model": _UNAVAIL,
        "gpu_vram_mb": _UNAVAIL,
        "driver_version": _UNAVAIL,
    }
    if not text:
        return unavailable
    lines = text.strip().splitlines()
    if not lines:
        return unavailable
    first = lines[0]
    parts = [p.strip() for p in first.split(",")]
    if len(parts) != 3:
        # 1, 2, 4 列など: クエリと一致しない -> 解析せず unavailable に倒す。
        # 4 列出力は `_run_nvidia_smi` のクエリ仕様上発生しないため
        # 「妥協してパース」せず、コマンド変更時に気付けるよう unavailable とする。
        return unavailable
    name, vram, drv = parts
    try:
        vram_int: str | int = int(vram)
    except ValueError:
        vram_int = _UNAVAIL
    return {
        "gpu_model": name or _UNAVAIL,
        "gpu_vram_mb": vram_int,
        "driver_version": drv or _UNAVAIL,
    }


def collect(data_dir: Path | None = None) -> dict[str, str | int | None]:
    """CPU / RAM / GPU / OS / Python / Disk 空き容量のスナップショットを返す。

    - PII を含まない (hostname / IP / MAC / ディスクパスは出力しない)。
    - 採取失敗キーは "<unavailable>" にフォールバックする。
    - `data_dir` が指定された場合はそのディスクの空き容量を、未指定時は HOME。
    """
    cpu_model = platform.processor() or _UNAVAIL
    cpu_threads_raw = os.cpu_count()
    cpu_threads: str | int = cpu_threads_raw if cpu_threads_raw else _UNAVAIL
    cpu_cores: str | int = cpu_threads
    if _psutil is not None:
        try:
            cpu_cores_val = _psutil.cpu_count(logical=False)
            cpu_cores = cpu_cores_val if cpu_cores_val else cpu_threads
        except Exception:  # 採取失敗は致命的でない (フォールバック)
            cpu_cores = cpu_threads

    ram_total: str | float
    ram_avail: str | float
    if _psutil is not None:
        try:
            vm = _psutil.virtual_memory()
            ram_total = round(vm.total / (1024 ** 3), 1)
            ram_avail = round(vm.available / (1024 ** 3), 1)
        except Exception:  # 採取失敗は致命的でない (フォールバック)
            ram_total = _UNAVAIL
            ram_avail = _UNAVAIL
    else:
        ram_total = _UNAVAIL
        ram_avail = _UNAVAIL

    gpu = _parse_nvidia_smi(_run_nvidia_smi())

    disk_free: str | float
    if _psutil is not None:
        try:
            probe = str(data_dir) if data_dir is not None else str(Path.home())
            du = _psutil.disk_usage(probe)
            disk_free = round(du.free / (1024 ** 3), 1)
        except Exception:  # 採取失敗は致命的でない (フォールバック)
            disk_free = _UNAVAIL
    else:
        disk_free = _UNAVAIL

    return {
        "cpu_model": cpu_model,
        "cpu_cores": cpu_cores,
        "cpu_threads": cpu_threads,
        "ram_total_gb": ram_total,
        "ram_available_gb": ram_avail,
        **gpu,
        "os_arch": platform.machine() or _UNAVAIL,
        "os_platform": platform.platform() or _UNAVAIL,
        "python_version": sys.version.split()[0],
        "disk_free_gb": disk_free,
    }

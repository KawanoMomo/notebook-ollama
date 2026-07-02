"""未送信クラッシュレポートの JSON 永続化レイヤ。

spec §6.1 / plan Sprint 2 Task 2.1。

保存先は ``data_dir/crash-pending/<id>.json``。書き込みは ``.tmp`` を経由した
``os.replace`` による atomic write で、書き込み途中の電源断や例外で既存ファイル
が破損しないことを保証する。読み込み側は不正な JSON / 欠損フィールドを持つ
ファイルを sil ently スキップするので、起動時に 1 件壊れていても他の pending
レポートはちゃんと拾える。
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Literal

Source = Literal[
    "fastapi",
    "excepthook",
    "signal",
    "atexit",
    "frontend",
    "unclean_shutdown",
]
"""クラッシュ検知元の識別子 (spec §4.1)。"""


_DIR_NAME = "crash-pending"


@dataclass
class PendingCrash:
    """1 件の未送信クラッシュレポート。

    JSON 永続化のため、`dataclasses.asdict` で安全にシリアライズできるよう、
    全フィールドを JSON-native 型 (str / list / dict) で保持する。
    """

    id: str
    fingerprint: str
    created_at: str  # ISO-8601 UTC (例: "2026-06-28T00:00:00Z")
    exception_type: str
    exception_message: str
    trace: list[str] = field(default_factory=list)
    hardware: dict = field(default_factory=dict)
    log_tail: list[dict] = field(default_factory=list)
    source: Source = "fastapi"


def _pending_dir(data_dir: Path) -> Path:
    return Path(data_dir) / _DIR_NAME


def _path_for(data_dir: Path, crash_id: str) -> Path:
    return _pending_dir(data_dir) / f"{crash_id}.json"


def save(data_dir: Path, crash: PendingCrash) -> Path:
    """atomic に 1 件保存し、確定後のファイルパスを返す。

    手順:
    1. ``crash-pending/`` を必要なら作成。
    2. 同階層に ``<id>.json.tmp`` を作って JSON を書き込み・fsync。
    3. ``os.replace`` で ``<id>.json`` にリネーム (POSIX/Win 両方で atomic)。
    4. リネーム失敗時は ``.tmp`` を片付けて例外を再送出 (元ファイルは無傷)。
    """
    pending_dir = _pending_dir(data_dir)
    pending_dir.mkdir(parents=True, exist_ok=True)
    target = _path_for(data_dir, crash.id)
    tmp = target.with_suffix(target.suffix + ".tmp")

    payload = json.dumps(asdict(crash), ensure_ascii=False, indent=2)
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        # 中断したら ``.tmp`` を片付ける (既存 target は無傷のまま)
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise
    return target


def _from_dict(data: dict) -> PendingCrash:
    """dict → PendingCrash。欠損フィールドがあれば ``KeyError`` を投げる。"""
    required = {f.name for f in fields(PendingCrash)}
    missing = required - data.keys()
    if missing:
        raise KeyError(f"missing fields: {sorted(missing)}")
    # 既知フィールドだけ拾うことで、将来追加フィールドの混入で落ちないようにする
    return PendingCrash(**{k: data[k] for k in required})


def _load_one(path: Path) -> PendingCrash | None:
    """1 ファイルを読み込む。壊れていれば ``None`` (呼び出し側で skip)。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.strip():
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        return _from_dict(data)
    except (KeyError, TypeError):
        return None


def load_all(data_dir: Path) -> list[PendingCrash]:
    """``crash-pending/`` 配下の全 JSON を ``created_at`` 降順で返す。

    壊れた JSON / 欠損フィールドのファイルは skip。起動時にこの関数で全件
    pickup されるため、1 件の破損で全体が読めなくなることを避ける。
    """
    pending_dir = _pending_dir(data_dir)
    if not pending_dir.is_dir():
        return []
    crashes: list[PendingCrash] = []
    for p in sorted(pending_dir.glob("*.json")):
        crash = _load_one(p)
        if crash is not None:
            crashes.append(crash)
    crashes.sort(key=lambda c: c.created_at, reverse=True)
    return crashes


def get(data_dir: Path, crash_id: str) -> PendingCrash | None:
    """指定 id の未送信レポートを返す (存在しなければ ``None``)。"""
    path = _path_for(data_dir, crash_id)
    if not path.is_file():
        return None
    return _load_one(path)


def delete(data_dir: Path, crash_id: str) -> bool:
    """指定 id の未送信レポートを削除。実在し削除に成功したら ``True``。"""
    path = _path_for(data_dir, crash_id)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return True

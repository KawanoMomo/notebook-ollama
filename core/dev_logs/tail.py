"""OllamaServerLogTail — ollama serve のログ tail(仕様 §8.4)。

- DevBroker の購読者が 1 人以上いるときだけ動く(NFR-4 / I12)
- 対象: %LOCALAPPDATA%/Ollama/server.log(存在しなければ warn 1 件で no-op)
- ローテーション/トランケート検知: サイズ減少で reopen し info を 1 件 push
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from core.dev_logs.broker import DevBroker
from core.dev_logs.ring import DevLogRing
from core.dev_logs.sink import push_dev_entry

_POLL_INTERVAL_S = 1.0


def default_server_log_path() -> Path | None:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return None
    return Path(base) / "Ollama" / "server.log"


class OllamaServerLogTail:
    def __init__(
        self,
        *,
        ring: DevLogRing,
        broker: DevBroker,
        path: Path | None = None,
    ) -> None:
        self._ring = ring
        self._broker = broker
        self._path = path if path is not None else default_server_log_path()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        # open と末尾 seek は start() 内で同期的に行う。これにより
        # 「start 時点以降の追記は必ず拾う」ことが確定する(スレッド起動の
        # 遅延中に追記された行を末尾 seek で読み飛ばすレースを防ぐ)。
        path = self._path
        if path is None or not path.exists():
            self._push(
                "warn", "server.log not found", {"path": str(path) if path else None}
            )
            return
        try:
            f = path.open("r", encoding="utf-8", errors="replace")
            f.seek(0, os.SEEK_END)
        except OSError:
            self._push("warn", "server.log not found", {"path": str(path)})
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, args=(f,), daemon=True, name="dev-ollama-tail"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------
    def _push(self, level: str, msg: str, payload: dict | None = None) -> None:
        push_dev_entry(
            ring=self._ring,
            broker=self._broker,
            level=level,
            source="server",
            msg=msg,
            payload=payload or {},
        )

    def _run(self, f) -> None:
        path = self._path
        assert path is not None  # start() で検証済み
        try:
            last_size = path.stat().st_size
            while not self._stop.wait(_POLL_INTERVAL_S):
                try:
                    size = path.stat().st_size
                except OSError:
                    size = -1
                if size < last_size:
                    # ローテーション / truncate → reopen(E4)
                    try:
                        f.close()
                        f = path.open("r", encoding="utf-8", errors="replace")
                        self._push("info", "rotated, reopened", {"path": str(path)})
                    except OSError:
                        self._push("warn", "server.log reopen failed", {"path": str(path)})
                        return
                last_size = max(size, 0)
                for line in f.readlines():
                    line = line.rstrip("\r\n")
                    if line:
                        self._push("info", line)
        finally:
            try:
                f.close()
            except OSError:
                pass

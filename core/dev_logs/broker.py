"""DevBroker — Dev パネル SSE 用の pub/sub(仕様 §7.5)。

- 購読者ごとに asyncio.Queue を持ち、publish を fan-out する
- publish は同期コード・別スレッド(logging / to_thread 内)からも呼ばれるため、
  event loop への引き渡しは loop.call_soon_threadsafe で行う
- slow consumer(queue が slow_limit 超)は queue を flush して gap を 1 件だけ残す(E5)
- on_first_sub / on_last_unsub は OllamaServerLogTail の start/stop に使う(I12)
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

_fallback_log = logging.getLogger("dev_logs")

_SLOW_LIMIT_DEFAULT = 1000


@dataclass
class Subscription:
    id: int
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)


class DevBroker:
    def __init__(self, *, slow_limit: int = _SLOW_LIMIT_DEFAULT) -> None:
        self._slow_limit = slow_limit
        self._subs: dict[int, Subscription] = {}
        self._ids = itertools.count(1)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._on_first: list[Callable[[], None]] = []
        self._on_last: list[Callable[[], None]] = []

    # ------------------------------------------------------------------
    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """lifespan 起動時に呼ぶ。publish_threadsafe の宛先 loop。"""
        self._loop = loop

    def on_first_sub(self, cb: Callable[[], None]) -> None:
        self._on_first.append(cb)

    def on_last_unsub(self, cb: Callable[[], None]) -> None:
        self._on_last.append(cb)

    # ------------------------------------------------------------------
    def subscribe(self) -> Subscription:
        with self._lock:
            sub = Subscription(id=next(self._ids))
            self._subs[sub.id] = sub
            became_first = len(self._subs) == 1
        if became_first:
            for cb in self._on_first:
                try:
                    cb()
                except Exception:  # noqa: S110 — フックの失敗で購読を壊さない
                    _fallback_log.warning("dev broker on_first_sub hook failed")
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        with self._lock:
            self._subs.pop(sub.id, None)
            became_empty = len(self._subs) == 0
        if became_empty:
            for cb in self._on_last:
                try:
                    cb()
                except Exception:  # noqa: S110
                    _fallback_log.warning("dev broker on_last_unsub hook failed")

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)

    # ------------------------------------------------------------------
    def publish_threadsafe(self, event: dict) -> None:
        """どのスレッドからでも安全に配信する。loop 未設定・停止済みなら黙って捨てる。"""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._fanout, event)
        except RuntimeError:
            # loop 停止中(シャットダウンレース)。Dev 側は本流を止めない(NFR-2)
            pass

    def _fanout(self, event: dict) -> None:
        with self._lock:
            subs = list(self._subs.values())
        for sub in subs:
            try:
                if sub.queue.qsize() >= self._slow_limit:
                    # E5: 遅い読み手はここまでの分を捨て、gap だけ残して以後を再開
                    while not sub.queue.empty():
                        sub.queue.get_nowait()
                    sub.queue.put_nowait(
                        {"event": "gap", "data": {"lost_until": event.get("data", {}).get("seq")}}
                    )
                sub.queue.put_nowait(event)
            except Exception:  # noqa: S110
                _fallback_log.warning("dev broker fanout failed for sub %s", sub.id)

    def shutdown_all(self) -> None:
        """設定 OFF 遷移時: 全購読者に shutdown を通知する(E8)。"""
        self.publish_threadsafe({"event": "shutdown", "data": {}})


# プロセス内 singleton
broker = DevBroker()

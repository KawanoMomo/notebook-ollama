from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any


class SseBroker:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    def subscribe(self, topic: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subs[topic].add(q)
        return q

    def unsubscribe(self, topic: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subs.get(topic, set()).discard(q)

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        # 開発者モード mirror(spec §8.3)。disabled 時は enabled チェック 1 回で
        # 抜ける。Dev 側の失敗は push_dev_entry 内で握り潰される(NFR-2)。
        from core.dev_logs.broker import broker as _dev_broker
        from core.dev_logs.ring import ring as _dev_ring
        from core.dev_logs.sink import push_dev_entry
        push_dev_entry(
            ring=_dev_ring,
            broker=_dev_broker,
            level="info",
            source="events",
            msg=topic,
            payload={"topic": topic, "payload": payload},
        )
        for q in list(self._subs.get(topic, set())):
            await q.put(payload)

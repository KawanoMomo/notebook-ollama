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
        for q in list(self._subs.get(topic, set())):
            await q.put(payload)

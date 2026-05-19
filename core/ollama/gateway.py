from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Protocol


class _ClientLike(Protocol):
    async def embed(self, *, model: str, text: str) -> list[float]: ...
    def chat_stream(
        self, *, model: str, messages: list[dict[str, str]], options: dict[str, Any] | None = None
    ) -> AsyncIterator[str]: ...


class OllamaGateway:
    """Serializes Ollama chat and embed calls to one concurrent each.

    Web UI chat, MCP ask, and ingestion embeddings all flow through here.
    """

    def __init__(self, *, client: _ClientLike) -> None:
        self._client = client
        self._chat_lock = asyncio.Lock()
        self._embed_lock = asyncio.Lock()

    async def embed(self, *, model: str, text: str) -> list[float]:
        async with self._embed_lock:
            return await self._client.embed(model=model, text=text)

    async def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        options: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        await self._chat_lock.acquire()
        try:
            async for tok in self._client.chat_stream(
                model=model, messages=messages, options=options
            ):
                yield tok
        finally:
            self._chat_lock.release()

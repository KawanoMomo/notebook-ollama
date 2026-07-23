from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Protocol


class _ClientLike(Protocol):
    async def embed(
        self, *, model: str, text: str, options: dict[str, Any] | None = None
    ) -> list[float]: ...
    def chat_stream(
        self, *, model: str, messages: list[dict[str, Any]], options: dict[str, Any] | None = None
    ) -> AsyncIterator[str]: ...


class OllamaGateway:
    """Serializes Ollama chat and embed calls to one concurrent each.

    Web UI chat, MCP ask, and ingestion embeddings all flow through here.
    """

    def __init__(
        self,
        *,
        client: _ClientLike,
        embedding_options: dict[str, Any] | None = None,
    ) -> None:
        self._client = client
        self._embedding_options = embedding_options or None
        self._chat_lock = asyncio.Lock()
        self._embed_lock = asyncio.Lock()

    async def embed(self, *, model: str, text: str) -> list[float]:
        async with self._embed_lock:
            return await self._client.embed(
                model=model, text=text, options=self._embedding_options
            )

    async def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        await self._chat_lock.acquire()
        try:
            async for tok in self._client.chat_stream(
                model=model, messages=messages, options=options, meta=meta
            ):
                yield tok
        finally:
            self._chat_lock.release()

    async def generate(
        self,
        *,
        model: str,
        prompt: str,
        options: dict[str, Any] | None = None,
    ) -> str:
        """Non-streaming text completion: accumulate the chat stream into a string."""
        from core.ollama.client import ThinkingChunk

        messages = [{"role": "user", "content": prompt}]
        parts: list[str] = []
        async for tok in self.chat_stream(model=model, messages=messages, options=options):
            if isinstance(tok, ThinkingChunk):
                continue  # 思考は本文に含めない
            parts.append(tok)
        return "".join(parts)


class _GatewayLike(Protocol):
    async def embed(self, *, model: str, text: str) -> list[float]: ...


_EMBEDDING_DIM_CACHE: dict[str, int] = {}


def reset_embedding_dim_cache() -> None:
    """テスト用: プロセス内キャッシュをクリアする。"""
    _EMBEDDING_DIM_CACHE.clear()


async def probe_embedding_dim(gateway: _GatewayLike, model: str) -> int:
    """短文を埋め込み、返りベクトルの長さ(次元)を返す。

    結果はプロセス内 dict にモデル名でキャッシュする。同一モデルの
    2 回目以降は Ollama を叩かずキャッシュ値を返す。
    """
    cached = _EMBEDDING_DIM_CACHE.get(model)
    if cached is not None:
        return cached
    vector = await gateway.embed(model=model, text="x")
    dim = len(vector)
    _EMBEDDING_DIM_CACHE[model] = dim
    return dim


class _ShowCapable(Protocol):
    async def show(self, model: str) -> dict[str, Any]: ...


_VISION_CAPABILITY_CACHE: dict[str, bool] = {}


def reset_vision_capability_cache() -> None:
    """テスト用: プロセス内キャッシュをクリアする。"""
    _VISION_CAPABILITY_CACHE.clear()


async def probe_vision_capability(client: _ShowCapable, model: str) -> bool:
    """モデルの vision capability を判定し、プロセス内 dict にキャッシュする。"""
    from core.ollama.models_info import has_vision_capability

    cached = _VISION_CAPABILITY_CACHE.get(model)
    if cached is not None:
        return cached
    show = await client.show(model)
    result = has_vision_capability(show.get("capabilities", []) or [])
    _VISION_CAPABILITY_CACHE[model] = result
    return result

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from core.exceptions import AppError, ErrorCode


class OllamaClient:
    def __init__(
        self,
        *,
        endpoint: str,
        timeout: float = 120.0,
        chat_read_timeout: float | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._timeout = timeout
        self._chat_read_timeout = chat_read_timeout

    async def embed(
        self,
        *,
        model: str,
        text: str,
        options: dict[str, Any] | None = None,
    ) -> list[float]:
        payload: dict[str, Any] = {"model": model, "prompt": text}
        if options:
            payload["options"] = options
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                r = await client.post(
                    f"{self._endpoint}/api/embeddings",
                    json=payload,
                )
            except httpx.HTTPError as exc:
                raise AppError(
                    ErrorCode.OLLAMA_UNREACHABLE,
                    "Ollama unreachable",
                    detail=str(exc),
                ) from exc
        if r.status_code == 404:
            raise AppError(ErrorCode.OLLAMA_MODEL_NOT_FOUND, f"model {model} not found")
        if r.status_code >= 400:
            raise AppError(
                ErrorCode.OLLAMA_GENERATION_FAILED,
                f"ollama returned {r.status_code}",
                detail=r.text,
            )
        data = r.json()
        return data["embedding"]

    async def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        options: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """トークンを逐次 yield する。meta が渡された場合、最終チャンクの
        done_reason("stop" / "length" 等)を meta["done_reason"] に書き込む。
        num_predict 上限による打ち切り検知に使う。"""
        payload = {"model": model, "messages": messages, "stream": True}
        if options:
            payload["options"] = options
        # connect/write/pool は httpx 既定(5s)を維持し、read のみ有限化する。
        # ストリーミング中の各トークン受信間隔に read タイムアウトが適用される。
        timeout = httpx.Timeout(5.0, read=self._chat_read_timeout)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                async with client.stream(
                    "POST", f"{self._endpoint}/api/chat", json=payload
                ) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        if response.status_code == 404:
                            raise AppError(
                                ErrorCode.OLLAMA_MODEL_NOT_FOUND, f"model {model} not found"
                            )
                        raise AppError(
                            ErrorCode.OLLAMA_GENERATION_FAILED,
                            f"ollama returned {response.status_code}",
                            detail=body.decode(errors="replace"),
                        )
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        chunk = json.loads(line)
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            yield content
                        if chunk.get("done"):
                            if meta is not None:
                                meta["done_reason"] = chunk.get("done_reason")
                            return
            except httpx.HTTPError as exc:
                raise AppError(
                    ErrorCode.OLLAMA_UNREACHABLE, "Ollama unreachable", detail=str(exc)
                ) from exc

    async def list_tags(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                r = await client.get(f"{self._endpoint}/api/tags")
            except httpx.HTTPError as exc:
                raise AppError(
                    ErrorCode.OLLAMA_UNREACHABLE, "Ollama unreachable", detail=str(exc)
                ) from exc
        r.raise_for_status()
        return r.json().get("models", [])

    async def show(self, model: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                r = await client.post(f"{self._endpoint}/api/show", json={"name": model})
            except httpx.HTTPError as exc:
                raise AppError(
                    ErrorCode.OLLAMA_UNREACHABLE, "Ollama unreachable", detail=str(exc)
                ) from exc
        if r.status_code == 404:
            raise AppError(ErrorCode.OLLAMA_MODEL_NOT_FOUND, f"model {model} not found")
        r.raise_for_status()
        return r.json()

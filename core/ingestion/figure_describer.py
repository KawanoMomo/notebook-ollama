"""図クロップの説明文生成(spec: 2026-07-20-vlm-figure-ocr-design.md §4/§9)。

OcrEngine/FigureDescriber はインターフェースとして分離し、将来の専用エンジン
差し替え(Unlimited-OCR等、スパイク結果次第)に備える(ADRドラフト
draft-2026-07-20-vlm-ocr-ollama-only)。
"""
from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Protocol

from core.logging import get_logger

log = get_logger("ingestion.figure_describer")

_PROMPT = (
    "この画像は文書中の図です。次を日本語で簡潔に述べてください: "
    "(1) 図の種別(グラフ/写真/回路図/配置図など) (2) 要点 "
    "(3) 読み取れる数値・ラベルがあれば列挙。"
)
_MIN_LENGTH = 5


class FigureDescriber(Protocol):
    async def describe(self, *, image_png: bytes) -> str | None: ...


class _ChatStreamLike(Protocol):
    def chat_stream(self, *, model, messages, options=None, meta=None): ...


class OllamaFigureDescriber:
    def __init__(self, *, client: _ChatStreamLike, model: str) -> None:
        self._client = client
        self._model = model

    async def _one_attempt(self, image_png: bytes) -> str | None:
        from core.ollama.messages import build_image_message

        b64 = base64.b64encode(image_png).decode("ascii")
        messages = [build_image_message(role="user", content=_PROMPT, images_b64=[b64])]
        try:
            chunks: list[str] = []
            async for tok in self._client.chat_stream(model=self._model, messages=messages):
                chunks.append(str(tok))
            text = "".join(chunks).strip()
        except Exception:
            log.warning("figure_describe_failed", exc_info=True)
            return None
        return text if len(text) >= _MIN_LENGTH else None

    async def describe(self, *, image_png: bytes) -> str | None:
        result = await self._one_attempt(image_png)
        if result is not None:
            return result
        log.info("figure_describe_empty_retry")
        return await self._one_attempt(image_png)


class LazyFigureDescriber:
    """vision_model / ベータフラグを呼び出し毎に再評価するラッパー。

    起動時に一度だけ model を bind する OllamaFigureDescriber と異なり、
    Settings 経由で vision_model が実行後に変更されても追従する
    (embedding_model_getter と同じ「値は起動時ではなく呼び出し時に読む」規約)。
    """

    def __init__(
        self,
        *,
        client: _ChatStreamLike,
        model_getter: Callable[[], str],
        enabled_getter: Callable[[], bool] | None = None,
    ) -> None:
        self._client = client
        self._model_getter = model_getter
        self._enabled_getter = enabled_getter

    async def describe(self, *, image_png: bytes) -> str | None:
        if self._enabled_getter is not None and not self._enabled_getter():
            return None
        model = self._model_getter()
        if not model:
            return None
        return await OllamaFigureDescriber(client=self._client, model=model).describe(
            image_png=image_png
        )

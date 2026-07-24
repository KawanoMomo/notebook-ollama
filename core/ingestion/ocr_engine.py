"""スキャンPDF(画像のみ)のページ全体OCR(spec §4/§9)。

図説明(figure_describer.py)と同じ Ollama VLM 経路を使うが、プロンプトが
異なる(図の要約ではなくページ全文の書き起こし)ため別インターフェースに分ける。
"""
from __future__ import annotations

import base64
from typing import Protocol

from core.logging import get_logger

log = get_logger("ingestion.ocr_engine")

_OCR_PROMPT = (
    "この画像はスキャン文書のページです。書かれている文章をそのまま日本語で"
    "書き起こしてください。レイアウトの説明や要約は不要です、本文のみを出力してください。"
)


class OcrEngine(Protocol):
    async def ocr_page(self, *, image_png: bytes) -> str | None: ...


class _ChatStreamLike(Protocol):
    def chat_stream(self, *, model, messages, options=None, meta=None): ...


class OllamaOcrEngine:
    def __init__(self, *, client: _ChatStreamLike, model: str) -> None:
        self._client = client
        self._model = model

    async def ocr_page(self, *, image_png: bytes) -> str | None:
        from core.ollama.messages import build_image_message

        b64 = base64.b64encode(image_png).decode("ascii")
        messages = [build_image_message(role="user", content=_OCR_PROMPT, images_b64=[b64])]
        try:
            chunks: list[str] = []
            async for tok in self._client.chat_stream(model=self._model, messages=messages):
                chunks.append(str(tok))
            text = "".join(chunks).strip()
        except Exception:
            log.warning("ocr_page_failed", exc_info=True)
            return None
        return text or None

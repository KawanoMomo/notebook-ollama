"""スキャンPDF(画像のみ)のページ全体OCR(spec §4/§9)。

図説明(figure_describer.py)と同じ Ollama VLM 経路を使うが、プロンプトが
異なる(図の要約ではなくページ全文の書き起こし)ため別インターフェースに分ける。
"""
from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Protocol

from core.logging import get_logger

log = get_logger("ingestion.ocr_engine")

_OCR_PROMPT = (
    "この画像はスキャン文書のページです。書かれている文章をそのまま日本語で"
    "書き起こしてください。レイアウトの説明や要約は不要です、本文のみを出力してください。"
)
_MIN_LENGTH = 10
# 生成長の上限。図説明より長い(ページ全文の書き起こし)ぶん多めに取るが、
# 無制限にはしない。無制限だと thinking 系モデルが推敲を続けて出力が
# 埋め込み上限を超える(実機FB 2026-07-27)。
_NUM_PREDICT = 2048
# 小型VLM(実機: llava:7b)は書き起こしを拒否したり要約に逃げたりすることがある。
# 拒否文はそのまま採用すると非空なので「成功」扱いになり、RAG索引を汚染する
# (evaluator実機確認: 拒否文/ハルシネーションがそのまま ready 化していた)。
_REFUSAL_MARKERS = (
    "申し訳",
    "できません",
    "ご理解",
    "cannot provide",
    "unable to",
    "i'm sorry",
    "i am sorry",
    "as an ai",
)


def _is_low_quality(text: str) -> bool:
    if len(text) < _MIN_LENGTH:
        return True
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in _REFUSAL_MARKERS)


class OcrEngine(Protocol):
    async def ocr_page(self, *, image_png: bytes) -> str | None: ...

    def is_available(self) -> bool:
        """OCR を実際に試行できるか(モデル設定済み かつ 機能有効)。

        無効なエンジンに問い合わせても全ページ None が返るだけで、呼び出し側
        からは「OCRしたが読めなかった」と区別できない。区別できないと
        「OCRでも読み取れませんでした」という誤ったエラーを、OCRを一度も
        試していない状況で出してしまう(実機FB 2026-07-26)。
        """
        ...


class _ChatStreamLike(Protocol):
    def chat_stream(self, *, model, messages, options=None, meta=None): ...


class OllamaOcrEngine:
    def __init__(self, *, client: _ChatStreamLike, model: str) -> None:
        self._client = client
        self._model = model

    async def _one_attempt(self, image_png: bytes) -> str | None:
        from core.ollama.client import ThinkingChunk
        from core.ollama.messages import build_image_message

        b64 = base64.b64encode(image_png).decode("ascii")
        messages = [build_image_message(role="user", content=_OCR_PROMPT, images_b64=[b64])]
        try:
            chunks: list[str] = []
            async for tok in self._client.chat_stream(
                model=self._model,
                messages=messages,
                options={"num_predict": _NUM_PREDICT},
            ):
                # thinking 系モデルの思考トークンは書き起こし本文ではない。
                # 除外しないと "Thinking Process: ..." "Wait, looking closely..."
                # がページ本文として索引に入る(実機FB 2026-07-27)。
                if isinstance(tok, ThinkingChunk):
                    continue
                chunks.append(str(tok))
            text = "".join(chunks).strip()
        except Exception:
            log.warning("ocr_page_failed", exc_info=True)
            return None
        if _is_low_quality(text):
            return None
        return text

    def is_available(self) -> bool:
        return bool(self._model)

    async def ocr_page(self, *, image_png: bytes) -> str | None:
        result = await self._one_attempt(image_png)
        if result is not None:
            return result
        log.info("ocr_page_low_quality_retry")
        return await self._one_attempt(image_png)


class LazyOcrEngine:
    """vision_model / ベータフラグを呼び出し毎に再評価するラッパー。

    起動時に一度だけ model を bind する OllamaOcrEngine と異なり、
    Settings 経由で vision_model が実行後に変更されても追従する
    (embedding_model_getter と同じ「値は起動時ではなく呼び出し時に読む」規約)。
    無効時(モデル未設定 or ベータOFF)は全ページで None を返す
    (呼び出し側は「OCRで1ページも書き起こせなかった」として扱う)。
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

    def is_available(self) -> bool:
        if self._enabled_getter is not None and not self._enabled_getter():
            return False
        return bool(self._model_getter())

    async def ocr_page(self, *, image_png: bytes) -> str | None:
        if not self.is_available():
            return None
        model = self._model_getter()
        return await OllamaOcrEngine(client=self._client, model=model).ocr_page(
            image_png=image_png
        )

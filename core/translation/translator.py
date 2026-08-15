"""選択範囲翻訳。既存の Ollama ゲートウェイをそのまま使う。

設計: docs/specs/2026-08-07-citation-evidence-ui-design.md §3.5
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Protocol

# 出典パネルでの選択範囲が対象。長すぎる入力は文脈を圧迫するうえ、
# 11GB 環境では待ち時間が体感を壊すので開始前に弾く。
MAX_TRANSLATE_CHARS = 4000

_LANG_NAMES = {"ja": "日本語", "en": "英語"}


class TextTooLongError(ValueError):
    """翻訳対象が長すぎる。"""


class ChatGateway(Protocol):
    def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        options: dict[str, Any] | None = ...,
        meta: dict[str, Any] | None = ...,
    ) -> AsyncIterator[str]: ...


def build_messages(text: str, target_lang: str) -> list[dict[str, str]]:
    lang = _LANG_NAMES.get(target_lang, target_lang)
    system = (
        f"あなたは技術文書の翻訳者です。与えられたテキストを{lang}に翻訳してください。"
        "訳文のみを出力し、前置き・注釈・原文の再掲はしないこと。"
        "専門用語と固有名詞は原語を括弧で併記してよい。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": text},
    ]


async def translate_stream(
    *, text: str, target_lang: str, model: str, gateway: ChatGateway
) -> AsyncIterator[str]:
    """訳文をトークン単位でストリームする。空文字なら何もせず終わる。"""
    stripped = text.strip()
    if not stripped:
        return
    if len(stripped) > MAX_TRANSLATE_CHARS:
        raise TextTooLongError(f"text too long: {len(stripped)} > {MAX_TRANSLATE_CHARS}")
    async for tok in gateway.chat_stream(
        model=model, messages=build_messages(stripped, target_lang)
    ):
        yield tok

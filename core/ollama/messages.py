"""Ollama /api/chat 向けメッセージ辞書の構築ヘルパー。

chat_stream はメッセージの中身を検査せず素通しするため、画像投入は
このヘルパーで images キー付きの辞書を組み立てるだけで実現できる
(core/ollama/client.py・gateway.py への機能追加は不要)。
"""
from __future__ import annotations

from typing import Any


def build_image_message(*, role: str, content: str, images_b64: list[str]) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": role, "content": content}
    if images_b64:
        msg["images"] = images_b64
    return msg

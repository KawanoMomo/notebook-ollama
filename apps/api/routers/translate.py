"""選択範囲翻訳の SSE エンドポイント(spec §3.5)。"""

from __future__ import annotations

import json
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.exceptions import AppError, ErrorCode
from core.generation.stream_registry import is_stream_running
from core.translation.translator import (
    MAX_TRANSLATE_CHARS,
    TextTooLongError,
    translate_stream,
)

router = APIRouter(prefix="/api/translate", tags=["translate"])


class TranslateRequest(BaseModel):
    text: str
    target_lang: str = "ja"
    model: str | None = None
    # 渡されたら、その会話が生成中のあいだは実行しない(VRAM の取り合いを避ける)。
    conversation_id: str | None = None


@router.post("")
async def translate(request: Request, body: TranslateRequest) -> StreamingResponse:
    ctx = request.app.state.ctx

    if body.conversation_id and is_stream_running(body.conversation_id):
        # 生成ストリーム中は第2段(埋め込み)と同じ理由でブロックする。
        raise AppError(ErrorCode.STORAGE_CONFLICT, "generation in progress")

    if len(body.text.strip()) > MAX_TRANSLATE_CHARS:
        # ストリームに乗せると FE 側で扱いにくいので、開始前に弾く。
        raise AppError(
            ErrorCode.INPUT_INVALID,
            f"text too long: {len(body.text.strip())} > {MAX_TRANSLATE_CHARS}",
        )

    model = body.model or ctx.config.ollama.default_model

    async def gen() -> AsyncIterator[str]:
        try:
            async for tok in translate_stream(
                text=body.text,
                target_lang=body.target_lang,
                model=model,
                gateway=ctx.ollama_gateway,
            ):
                yield f"data: {json.dumps({'text': tok}, ensure_ascii=False)}\n\n"
        except TextTooLongError as exc:
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001 - 閲覧を止めないため理由を返して終える
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")

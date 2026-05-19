from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from core.storage import notebooks_repo


router = APIRouter(prefix="/api/notebooks", tags=["events"])


@router.get("/{notebook_id}/events")
async def stream_events(request: Request, notebook_id: str):
    ctx = request.app.state.ctx
    notebooks_repo.get_notebook(ctx.conn, notebook_id)
    topic = f"notebook:{notebook_id}"
    queue = ctx.sse.subscribe(topic)

    async def gen() -> AsyncIterator[dict]:
        try:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                    yield {"event": "source_status", "data": json.dumps(payload, ensure_ascii=False)}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": ""}
        finally:
            ctx.sse.unsubscribe(topic, queue)

    return EventSourceResponse(gen())

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/recordings/{rid}/live")
async def recording_live(ws: WebSocket, rid: str):
    """Stream live-caption preview events (captions, levels, errors) for an
    active recording to the client.

    The queue is populated by the recording start path; if there is no active
    recording (or no queue), we tell the client and close.
    """
    await ws.accept()
    ctx = ws.app.state.ctx
    sess = ctx.recordings.get(rid)
    q = sess.extras.get("queue") if sess else None
    if q is None:
        await ws.send_json({"error": "no active live caption for recording"})
        await ws.close()
        return
    try:
        while True:
            # Drain the sync queue from the event loop via a worker thread.
            try:
                msg = await asyncio.to_thread(q.get, True, 1.0)
            except Exception:
                # timeout / queue Empty — if the recording was stopped (removed
                # from the registry) we exit; otherwise keep waiting.
                if ctx.recordings.get(rid) is None:
                    return
                continue
            await ws.send_json(msg)
    except WebSocketDisconnect:
        return

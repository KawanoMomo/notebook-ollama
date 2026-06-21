from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.recording.mute_state import handle_mute_command

router = APIRouter()


def _now_ms(sess) -> int:
    """録音開始(t0)からの相対 ms。t0 未設定(古いセッション)なら 0。"""
    t0 = sess.extras.get("t0") if sess else None
    if t0 is None:
        return 0
    return int((time.perf_counter() - t0) * 1000)


@router.websocket("/ws/recordings/{rid}/live")
async def recording_live(ws: WebSocket, rid: str):
    """Stream live-caption preview events (captions, levels, errors) for an
    active recording to the client, AND receive client→server control messages.

    Server→client (existing): caption / level / info / error.
    Client→server (new): ``{"type":"mute","channel":"mic"|"system","muted":bool}``
    — opens/closes a per-channel mute interval and gates the live STT feed. The
    server echoes ``{"type":"mute_state","channel":...,"muted":...}`` back so the
    UI can sync (plus a ``level`` 0 for the muted channel to grey out its meter).

    Backward compatible: a client that never sends a "mute" message behaves
    exactly as before (pure server→client streaming).

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

    async def pump_outgoing() -> None:
        """Drain the sync caption/level queue and forward to the client."""
        while True:
            try:
                msg = await asyncio.to_thread(q.get, True, 1.0)
            except Exception:
                # timeout / queue Empty — if the recording was stopped (removed
                # from the registry) we exit; otherwise keep waiting.
                if ctx.recordings.get(rid) is None:
                    return
                continue
            await ws.send_json(msg)

    async def pump_incoming() -> None:
        """Receive client control messages (currently only "mute")."""
        while True:
            msg = await ws.receive_json()
            cur = ctx.recordings.get(rid)
            if cur is None:
                return  # recording stopped
            mute_state = cur.extras.get("mute_state")
            if mute_state is None:
                continue  # session has no mute state (shouldn't happen) -> ignore
            echo = handle_mute_command(mute_state, msg, _now_ms(cur))
            if echo is None:
                continue  # unknown type/channel/missing field -> ignored
            # Echo mute_state so the UI can sync, plus a level 0 for the muted
            # channel so its meter greys out immediately (we stop feeding real
            # levels for muted channels at the recorder callback).
            await ws.send_json(echo)
            if echo["muted"]:
                await ws.send_json(
                    {"type": "level", "channel": echo["channel"],
                     "rms_db": -80.0, "peak_db": -80.0}
                )

    out_task = asyncio.create_task(pump_outgoing())
    in_task = asyncio.create_task(pump_incoming())
    try:
        # Whichever pump finishes first (client disconnect / recording stopped /
        # error) ends the session; the other is then cancelled.
        await asyncio.wait({out_task, in_task}, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        for t in (out_task, in_task):
            if not t.done():
                t.cancel()
        # Await cancellation so tasks don't leak; swallow cancellation and normal
        # disconnects (a client closing the socket is expected teardown).
        for t in (out_task, in_task):
            try:
                await t
            except (asyncio.CancelledError, WebSocketDisconnect):
                pass
            except Exception:
                pass

from __future__ import annotations

import shutil

from fastapi import APIRouter, HTTPException, Request

from apps.api.schemas.recording import RecordingStarted, StartRecording
from core.recording.session import RecordingBusyError
from core.storage import notebooks_repo, sources_repo

router = APIRouter(tags=["recordings"])


def _make_recorder(ctx, session_dir):
    factory = getattr(ctx, "recorder_factory", None)
    if factory is not None:
        return factory(session_dir)
    from core.recording.recorder import Recorder
    return Recorder(session_dir=session_dir, sample_rate=ctx.config.audio.sample_rate)


def _get_transcriber(request):
    """Lazily build (and cache on app state) the shared whisper transcriber.

    Created on first live-caption recording so the model load cost is only paid
    when live captions are actually requested.
    """
    tr = getattr(request.app.state, "transcriber", None)
    if tr is None:
        from core.recording.transcriber import Transcriber
        a = request.app.state.ctx.config.audio
        tr = Transcriber(
            model_size=a.whisper_model, device=a.device, compute_type=a.compute_type
        )
        request.app.state.transcriber = tr
    return tr


@router.get("/api/audio-devices")
async def audio_devices():
    try:
        from core.recording.recorder import list_input_devices
        return list_input_devices()
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"recording extras not installed: {e}")


@router.post("/api/notebooks/{notebook_id}/recordings", response_model=RecordingStarted)
async def start_recording(request: Request, notebook_id: str, body: StartRecording):
    ctx = request.app.state.ctx
    notebooks_repo.get_notebook(ctx.conn, notebook_id)
    src = sources_repo.create_source(
        ctx.conn, notebook_id=notebook_id, kind="recording", title=None, origin="録音"
    )
    session_dir = ctx.config.sources_dir / src.id
    session_dir.mkdir(parents=True, exist_ok=True)
    try:
        sess = ctx.recordings.start(
            notebook_id, session_dir,
            lambda: _make_recorder(ctx, session_dir),
            live_caption=body.live_caption,
        )
    except RecordingBusyError as e:
        ctx.conn.execute("DELETE FROM sources WHERE id=?", (src.id,))
        shutil.rmtree(session_dir, ignore_errors=True)
        raise HTTPException(status_code=409, detail=str(e))
    sess.extras["source_id"] = src.id

    # --- Live caption wiring (PREVIEW ONLY) -------------------------------
    # Captions produced here are a low-latency preview; the high-accuracy RAG
    # transcript is built later by the offline pipeline. We accumulate caption
    # messages in live_segments for that future offline persistence step.
    import queue as _queue
    import time as _time

    from core.recording.levels import LevelMeter
    from core.recording.live_caption import LiveCaption

    cap_queue: _queue.Queue = _queue.Queue()
    live_segments: list[dict] = []

    def push_to_queue(msg):
        if msg.get("type") == "caption":
            live_segments.append(msg)
        try:
            cap_queue.put_nowait(msg)
        except Exception:
            pass

    sess.extras["queue"] = cap_queue
    sess.extras["live_segments"] = live_segments

    mic_lc = sys_lc = None
    live_active = False
    if body.live_caption:
        try:
            tr = _get_transcriber(request)
            epoch = _time.perf_counter()
            a = ctx.config.audio
            mic_lc = LiveCaption(
                transcriber=tr, on_caption=push_to_queue, label="あなた",
                epoch=epoch, id_prefix="mic", agc_enabled=a.agc_enabled,
            )
            sys_lc = LiveCaption(
                transcriber=tr, on_caption=push_to_queue, label="相手",
                epoch=epoch, id_prefix="sys", agc_enabled=a.agc_enabled,
            )
            mic_lc.start()
            sys_lc.start()
            sess.extras["live_captions"] = [mic_lc, sys_lc]
            live_active = True
        except Exception as exc:
            push_to_queue({
                "type": "error",
                "msg": f"live caption init failed: {type(exc).__name__}: {exc}",
            })
            mic_lc = sys_lc = None
            live_active = False

    mic_meter = LevelMeter("mic", push_to_queue, min_interval_ms=50)
    sys_meter = LevelMeter("system", push_to_queue, min_interval_ms=50)

    def on_mic_chunk(samples):
        mic_meter(samples)
        if mic_lc is not None:
            mic_lc.accept(samples)

    def on_system_chunk(samples):
        sys_meter(samples)
        if sys_lc is not None:
            sys_lc.accept(samples)

    try:
        sess.recorder.start(
            mic_index=body.mic_device_index, system_index=body.system_device_index,
            mic_on_chunk=on_mic_chunk, system_on_chunk=on_system_chunk,
        )
    except Exception as exc:
        # Recorder failed to open the device(s). Roll back the registered session
        # so the registry is freed (otherwise active_id stays non-None forever and
        # every future POST returns 409), mark the source failed, and clean up the
        # empty session dir. Also stop any live-caption workers we started above.
        for _lc in (mic_lc, sys_lc):
            if _lc is not None:
                try:
                    _lc.stop()
                except Exception:
                    pass
        ctx.recordings.pop(sess.id)
        sources_repo.update_source_status(
            ctx.conn, src.id,
            status=sources_repo.SourceStatus.ERROR, error_msg=str(exc),
        )
        shutil.rmtree(session_dir, ignore_errors=True)
        raise HTTPException(
            status_code=500, detail=f"failed to start recording: {exc}"
        )
    return RecordingStarted(
        recording_id=sess.id, source_id=src.id, status="recording",
        live_caption=live_active,
    )


@router.post("/api/notebooks/{notebook_id}/recordings/{rid}/stop")
async def stop_recording(request: Request, notebook_id: str, rid: str):
    ctx = request.app.state.ctx
    sess = ctx.recordings.get(rid)
    if sess is None:
        raise HTTPException(status_code=400, detail="not recording")
    if sess.notebook_id != notebook_id:
        raise HTTPException(status_code=404, detail="recording not in notebook")
    ctx.recordings.pop(rid)
    # Stop the live-caption workers (if any) before the recorder so they don't
    # keep accepting chunks after the audio stream closes.
    for _lc in sess.extras.get("live_captions", []) or []:
        try:
            _lc.stop()
        except Exception:
            pass
    paths = sess.recorder.stop()
    sess.extras["paths"] = {k: (str(v) if v else None) for k, v in paths.items()}
    # Offline pipeline wiring comes in a later task; for now just return stopped state.
    return {
        "recording_id": rid,
        "source_id": sess.extras.get("source_id"),
        "status": "pending",
        "paths": sess.extras["paths"],
    }


@router.put("/api/notebooks/{notebook_id}/recordings/{rid}/live-gain")
async def live_gain(request: Request, notebook_id: str, rid: str):
    """Set the manual boost (dB) applied to mic/system live caption workers.

    Values are clamped to [0, manual_boost_max_db]. Returns ok even when there
    are no live-caption workers (e.g. live_caption=false): the clamp result is
    still echoed back.
    """
    ctx = request.app.state.ctx
    sess = ctx.recordings.get(rid)
    if sess is None:
        raise HTTPException(status_code=404, detail="no active recording")
    body = await request.json()
    mx = ctx.config.audio.manual_boost_max_db

    def clamp(v):
        return max(0.0, min(mx, float(v)))

    mic_db = clamp(body.get("mic_db", 0.0))
    sys_db = clamp(body.get("sys_db", 0.0))
    for lc in sess.extras.get("live_captions", []) or []:
        prefix = getattr(lc, "_id_prefix", "")
        lc.set_boost_db(mic_db if prefix == "mic" else sys_db)
    return {"ok": True, "mic_db": mic_db, "sys_db": sys_db}

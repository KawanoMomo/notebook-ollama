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
    try:
        sess.recorder.start(
            mic_index=body.mic_device_index, system_index=body.system_device_index
        )
    except Exception as exc:
        # Recorder failed to open the device(s). Roll back the registered session
        # so the registry is freed (otherwise active_id stays non-None forever and
        # every future POST returns 409), mark the source failed, and clean up the
        # empty session dir.
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
        live_caption=body.live_caption,
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
    paths = sess.recorder.stop()
    sess.extras["paths"] = {k: (str(v) if v else None) for k, v in paths.items()}
    # Offline pipeline wiring comes in a later task; for now just return stopped state.
    return {
        "recording_id": rid,
        "source_id": sess.extras.get("source_id"),
        "status": "pending",
        "paths": sess.extras["paths"],
    }

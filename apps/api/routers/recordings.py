from __future__ import annotations

import shutil

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from apps.api.routers.audio import _resolve_audio_path
from apps.api.schemas.recording import RecordingStarted, StartRecording
from core.recording.session import RecordingBusyError
from core.storage import notebooks_repo, sources_repo
from core.storage.chunks_repo import delete_chunks_for_source

router = APIRouter(tags=["recordings"])


def _make_recorder(ctx, session_dir):
    factory = getattr(ctx, "recorder_factory", None)
    if factory is not None:
        return factory(session_dir)
    from core.recording.recorder import Recorder
    return Recorder(session_dir=session_dir, sample_rate=ctx.config.audio.sample_rate)


def _get_transcriber(request):
    """Lazily build (and cache on app state) the shared whisper transcriber.

    Created on first live-caption recording (or offline stop) so the model load
    cost is only paid when transcription is actually requested. The same cached
    instance backs both live captions and the offline pipeline.

    Honors a test hook: if ``ctx.transcriber_factory`` is set, it is used to
    build the cached transcriber instead of constructing the real one (so tests
    never load a whisper model).
    """
    tr = getattr(request.app.state, "transcriber", None)
    if tr is None:
        ctx = request.app.state.ctx
        fac = getattr(ctx, "transcriber_factory", None)
        if fac is not None:
            tr = fac()
        else:
            from core.recording.transcriber import Transcriber
            a = ctx.config.audio
            tr = Transcriber(
                model_size=a.whisper_model, device=a.device, compute_type=a.compute_type
            )
        request.app.state.transcriber = tr
    return tr


def _get_diarizer(request):
    """Lazily build the speaker diarizer for the offline pipeline.

    Returns None when diarization is disabled or the ONNX models are not present
    on disk, so the pipeline degrades gracefully to single-speaker mode. Honors a
    test hook (``ctx.diarizer_factory``) so tests never load a real model.
    """
    ctx = request.app.state.ctx
    fac = getattr(ctx, "diarizer_factory", None)
    if fac is not None:
        return fac()
    cfg = ctx.config.audio
    if not cfg.diarization_enabled:
        return None
    from pathlib import Path
    seg = cfg.diarizer_segmentation_model or str(
        ctx.config.data_dir / "models" / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"
    )
    emb = cfg.diarizer_embedding_model or str(
        ctx.config.data_dir / "models" / "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
    )
    if not (Path(seg).exists() and Path(emb).exists()):
        return None  # models not present -> pipeline degrades to no-diarization
    try:
        from core.recording.diarizer import SherpaDiarizer
        # SherpaDiarizer.__init__(segmentation_model, embedding_model, threshold,
        # num_clusters, ...). max_speakers None -> -1 (auto cluster count).
        num_clusters = cfg.max_speakers if cfg.max_speakers is not None else -1
        return SherpaDiarizer(
            segmentation_model=seg,
            embedding_model=emb,
            threshold=cfg.diarizer_threshold,
            num_clusters=num_clusters,
        )
    except Exception:
        return None


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


def _resolve_wav(p) -> "Path | None":
    """Return Path(p) only if the file exists and is non-trivial (>64 bytes).

    A zero-byte (or header-only) wav means that channel never captured audio;
    treat it as absent so the offline pipeline doesn't transcribe an empty file.
    """
    from pathlib import Path
    if not p:
        return None
    path = Path(p)
    try:
        if path.exists() and path.stat().st_size > 64:
            return path
    except OSError:
        return None
    return None


def _dispatch_recording_pipeline(
    request: Request,
    background: BackgroundTasks,
    *,
    notebook_id: str,
    source_id: str,
    mic_audio,
    system_audio,
) -> None:
    """録音オフラインパイプラインを background task として投入する(stop / retry 共通)。

    mic_audio / system_audio は解決済みの Path | None。少なくとも一方は非 None で
    あること(呼び出し側で検証)。現行 AudioSettings と共有 transcriber/diarizer を
    流用し、source を PARSING にしてから dispatch する。
    """
    ctx = request.app.state.ctx
    a = ctx.config.audio
    model = ctx.config.ollama.default_model
    transcriber = _get_transcriber(request)
    diarizer = _get_diarizer(request)
    sources_repo.update_source_status(
        ctx.conn, source_id, status=sources_repo.SourceStatus.PARSING
    )
    background.add_task(
        ctx.recording_pipeline.run,
        source_id=source_id,
        notebook_id=notebook_id,
        mic_wav=mic_audio,
        system_wav=system_audio,
        transcriber=transcriber,
        diarizer=diarizer,
        model=model,
        diarization_enabled=(a.diarization_enabled and diarizer is not None),
        name_inference_enabled=a.name_inference_llm,
        name_threshold=a.name_threshold,
        storage_format=a.storage_format,
        storage_bitrate_kbps=a.storage_bitrate_kbps,
        keep_audio=a.keep_audio,
        auto_title_enabled=a.auto_title,
    )


@router.post("/api/notebooks/{notebook_id}/recordings/{rid}/stop")
async def stop_recording(
    request: Request, notebook_id: str, rid: str, background: BackgroundTasks
):
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

    # --- Dispatch the offline RAG ingestion pipeline as a background task -----
    mic_wav = _resolve_wav(paths.get("mic"))
    system_wav = _resolve_wav(paths.get("system"))

    src_id = sess.extras.get("source_id")
    _dispatch_recording_pipeline(
        request,
        background,
        notebook_id=notebook_id,
        source_id=src_id,
        mic_audio=mic_wav,
        system_audio=system_wav,
    )
    return {
        "recording_id": rid,
        "source_id": src_id,
        "status": "processing",
        "paths": sess.extras["paths"],
    }


@router.post("/api/notebooks/{notebook_id}/recordings/{source_id}/retry")
async def retry_recording(
    request: Request, notebook_id: str, source_id: str, background: BackgroundTasks
):
    """既に変換済みの圧縮音源(.m4a/.opus/.mp3/.wav)からオフライン RAG パイプラインを
    再実行する。0チャンクや error で終わった録音の再埋め込み手段。

    チャンネル別に音源を解決し、両方欠如なら 422。既存チャンク(sqlite + ベクタ)を
    クリアして PARSING にし、stop と同じ dispatch を再利用する。
    """
    from core.exceptions import AppError

    ctx = request.app.state.ctx
    try:
        src = sources_repo.get_source(ctx.conn, source_id)
    except AppError:
        raise HTTPException(status_code=404, detail="source not found")
    if src.notebook_id != notebook_id:
        raise HTTPException(status_code=404, detail="source not in notebook")
    if src.kind != "recording":
        raise HTTPException(status_code=422, detail="source is not a recording")

    base = ctx.config.sources_dir / source_id
    mic_audio = _resolve_audio_path(base, "mic") if base.is_dir() else None
    system_audio = _resolve_audio_path(base, "system") if base.is_dir() else None
    if mic_audio is None and system_audio is None:
        raise HTTPException(status_code=422, detail="no audio to re-embed")

    # 既存チャンクをクリア(sqlite + ベクタ)
    delete_chunks_for_source(ctx.conn, source_id)
    ctx.vector_store.delete_by_source(source_id)

    _dispatch_recording_pipeline(
        request,
        background,
        notebook_id=notebook_id,
        source_id=source_id,
        mic_audio=mic_audio,
        system_audio=system_audio,
    )
    return {"source_id": source_id, "status": "processing"}


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

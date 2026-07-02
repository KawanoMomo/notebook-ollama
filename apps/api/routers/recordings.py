from __future__ import annotations

import contextlib
import shutil
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from apps.api.routers.audio import _resolve_audio_path
from apps.api.schemas.recording import RecordingStarted, StartRecording
from core.recording.session import RecordingBusyError
from core.storage import notebooks_repo, sources_repo
from core.storage.chunks_repo import delete_chunks_for_source

router = APIRouter(tags=["recordings"])

_RECORDING_EXTRA_HINT = (
    "recording extras not installed; run `uv sync --extra recording` to enable"
)


def _require_recording_pipeline(ctx) -> None:
    """録音 extra が入っていない場合は 503 で即時返す。

    `apps/api/dependencies.py` は recording 依存が欠落した環境でも起動できるよう
    recording_pipeline を None にして起動する(README で recording は opt-in)。
    録音/再変換/停止は録音 extra を実際に必要とするので、None なら 503 を返す。
    """
    if getattr(ctx, "recording_pipeline", None) is None:
        raise HTTPException(status_code=503, detail=_RECORDING_EXTRA_HINT)


def _make_recorder(ctx, session_dir):
    factory = getattr(ctx, "recorder_factory", None)
    if factory is not None:
        return factory(session_dir)
    from core.recording.recorder import Recorder
    return Recorder(session_dir=session_dir, sample_rate=ctx.config.audio.sample_rate)


def _get_transcriber(request):
    """Lazily resolve the shared whisper transcriber for live + offline use.

    Resolution order (highest priority first):

    1. ``ctx.transcriber_factory`` — legacy 0-arg test hook used by
       ``tests/integration/test_api/test_recordings_api.py`` and
       ``test_recording_stop_dispatch.py`` to inject a fake transcriber
       AFTER lifespan startup. Preserved verbatim so the existing test
       suite stays GREEN.
    2. ``ctx.transcriber`` (Sprint 3 DI) — a lazy property on AppContext
       that builds via ``ctx.backend_factory.build_transcriber(...)``.
       The factory wraps the existing ``Transcriber`` class with
       identical constructor args, so behaviour is preserved.

    The transcriber is cached on ``app.state.transcriber`` so live captions
    and the offline pipeline share a single WhisperModel load.
    """
    tr = getattr(request.app.state, "transcriber", None)
    if tr is None:
        ctx = request.app.state.ctx
        fac = getattr(ctx, "transcriber_factory", None)
        if fac is not None:
            tr = fac()
        else:
            # Sprint 3 DI path — ctx.transcriber is the lazy @property on
            # AppContext, backed by ctx.backend_factory.build_transcriber.
            tr = ctx.transcriber
        request.app.state.transcriber = tr
    return tr


def _get_diarizer(request):
    """Lazily resolve the speaker diarizer for the offline pipeline.

    Returns ``None`` when diarization is disabled or the ONNX models are not
    present on disk, so the pipeline degrades gracefully to single-speaker
    mode. Resolution order mirrors :func:`_get_transcriber`:

    1. ``ctx.diarizer_factory`` — legacy 0-arg test hook.
    2. ``ctx.diarizer`` (Sprint 3 DI) — lazy property on AppContext that
       builds via ``ctx.backend_factory.build_diarizer(...)`` with the model
       paths resolved from ``ctx.config.audio`` (and the disk-existence
       check applied inside the property so the Factory stays I/O-free).
    """
    ctx = request.app.state.ctx
    fac = getattr(ctx, "diarizer_factory", None)
    if fac is not None:
        return fac()
    # Sprint 3 DI path — ctx.diarizer is the lazy @property on AppContext.
    return ctx.diarizer


@router.get("/api/audio-devices")
async def audio_devices():
    try:
        from core.recording.recorder import list_input_devices
        return list_input_devices()
    except ImportError as e:
        raise HTTPException(
            status_code=503, detail=f"recording extras not installed: {e}"
        ) from e


@router.post("/api/notebooks/{notebook_id}/recordings", response_model=RecordingStarted)
async def start_recording(request: Request, notebook_id: str, body: StartRecording):
    ctx = request.app.state.ctx
    _require_recording_pipeline(ctx)
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
        raise HTTPException(status_code=409, detail=str(e)) from e
    sess.extras["source_id"] = src.id

    # --- Live caption wiring (PREVIEW ONLY) -------------------------------
    # Captions produced here are a low-latency preview; the high-accuracy RAG
    # transcript is built later by the offline pipeline. We accumulate caption
    # messages in live_segments for that future offline persistence step.
    import queue as _queue
    import time as _time

    from core.recording.levels import LevelMeter
    from core.recording.live_caption import LiveCaption
    from core.recording.mute_state import MuteState

    cap_queue: _queue.Queue = _queue.Queue()
    live_segments: list[dict] = []

    def push_to_queue(msg):
        if msg.get("type") == "caption":
            live_segments.append(msg)
        with contextlib.suppress(Exception):
            cap_queue.put_nowait(msg)

    sess.extras["queue"] = cap_queue
    sess.extras["live_segments"] = live_segments
    # --- Channel mute state -----------------------------------------------
    # ミュートは「録音側で無音書き込み」方式(設計確定 2026-06-23)。ミュート中は
    # recorder が当該チャンネルの WAV に無音を書くため、ミュート区間は STT 以降の
    # 全工程に到達しない。mute_state は現在のミュート真偽値をチャンネル別に保持する
    # だけ(WS が更新、recorder と live STT ゲートが参照)。区間タイムスタンプや
    # mute_intervals.json は不要(ループバックの無音ドロップで WAV 時間軸が圧縮され、
    # 壁時計→WAV の写像が非線形になるため、タイムスタンプ方式は採らない)。
    sess.extras["mute_state"] = MuteState()

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

    mute_state = sess.extras["mute_state"]

    # Live STT gating: ミュート中チャンネルのフレームは live STT に渡さず、レベルメータも
    # 止める(WS 側で level 0 をエコーして UI をグレーアウトする)。is_muted は内部で
    # ロックを取るのでスレッド安全。なお recorder は同じ mute_state を見てミュート中の
    # WAV を無音化するため、オフライン側もミュート区間は自動的に除外される。
    def on_mic_chunk(samples):
        if mute_state.is_muted("mic"):
            return
        mic_meter(samples)
        if mic_lc is not None:
            mic_lc.accept(samples)

    def on_system_chunk(samples):
        if mute_state.is_muted("system"):
            return
        sys_meter(samples)
        if sys_lc is not None:
            sys_lc.accept(samples)

    try:
        sess.recorder.start(
            mic_index=body.mic_device_index, system_index=body.system_device_index,
            mic_on_chunk=on_mic_chunk, system_on_chunk=on_system_chunk,
            mic_mute_check=lambda: mute_state.is_muted("mic"),
            system_mute_check=lambda: mute_state.is_muted("system"),
        )
    except Exception as exc:
        # Recorder failed to open the device(s). Roll back the registered session
        # so the registry is freed (otherwise active_id stays non-None forever and
        # every future POST returns 409), mark the source failed, and clean up the
        # empty session dir. Also stop any live-caption workers we started above.
        for _lc in (mic_lc, sys_lc):
            if _lc is not None:
                with contextlib.suppress(Exception):
                    _lc.stop()
        ctx.recordings.pop(sess.id)
        sources_repo.update_source_status(
            ctx.conn, src.id,
            status=sources_repo.SourceStatus.ERROR, error_msg=str(exc),
        )
        shutil.rmtree(session_dir, ignore_errors=True)
        raise HTTPException(
            status_code=500, detail=f"failed to start recording: {exc}"
        ) from exc
    return RecordingStarted(
        recording_id=sess.id, source_id=src.id, status="recording",
        live_caption=live_active,
    )


def _resolve_wav(p) -> Path | None:
    """Return Path(p) only if the file exists and is non-trivial (>64 bytes).

    A zero-byte (or header-only) wav means that channel never captured audio;
    treat it as absent so the offline pipeline doesn't transcribe an empty file.
    """
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
    _require_recording_pipeline(ctx)
    sess = ctx.recordings.get(rid)
    if sess is None:
        raise HTTPException(status_code=400, detail="not recording")
    if sess.notebook_id != notebook_id:
        raise HTTPException(status_code=404, detail="recording not in notebook")
    ctx.recordings.pop(rid)
    # Stop the live-caption workers (if any) before the recorder so they don't
    # keep accepting chunks after the audio stream closes.
    for _lc in sess.extras.get("live_captions", []) or []:
        with contextlib.suppress(Exception):
            _lc.stop()
    paths = sess.recorder.stop()
    sess.extras["paths"] = {k: (str(v) if v else None) for k, v in paths.items()}

    # ミュート区間は recorder が録音時に無音化済み(録音側ミュート)。サイドカー JSON や
    # オフラインのタイムスタンプ除外は不要(下流の STT がミュート区間=無音から何も
    # 起こさない)。

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
    _require_recording_pipeline(ctx)
    try:
        src = sources_repo.get_source(ctx.conn, source_id)
    except AppError as exc:
        raise HTTPException(status_code=404, detail="source not found") from exc
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


@router.post("/api/notebooks/{notebook_id}/recordings/{source_id}/cancel")
async def cancel_recording(request: Request, notebook_id: str, source_id: str):
    """進行中のオフライン変換に停止を要求する。

    パイプラインは次のチェックポイント(ステップ境界 / 埋め込みループ)で中断し、
    status=error("変換を停止しました") に落ちる。即時の UI フィードバックのため、
    処理中(parsing/chunking/embedding)なら即座に error へ反映する(変換チェックが
    処理中状態を上書きしないよう、パイプライン側は status 書き込み前に停止を見る)。
    同期 STT の最中だけはその呼び出しが返るまで停止が効かない。
    """
    from core.exceptions import AppError

    ctx = request.app.state.ctx
    try:
        src = sources_repo.get_source(ctx.conn, source_id)
    except AppError as exc:
        raise HTTPException(status_code=404, detail="source not found") from exc
    if src.notebook_id != notebook_id:
        raise HTTPException(status_code=404, detail="source not in notebook")
    if src.kind != "recording":
        raise HTTPException(status_code=422, detail="source is not a recording")

    pipeline = getattr(ctx, "recording_pipeline", None)
    if pipeline is not None and hasattr(pipeline, "request_cancel"):
        pipeline.request_cancel(source_id)

    processing = {
        sources_repo.SourceStatus.PARSING,
        sources_repo.SourceStatus.CHUNKING,
        sources_repo.SourceStatus.EMBEDDING,
    }
    if src.status in processing:
        sources_repo.update_source_status(
            ctx.conn, source_id,
            status=sources_repo.SourceStatus.ERROR, error_msg="変換を停止しました",
        )
    return {"source_id": source_id, "status": "error", "cancelled": True}


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

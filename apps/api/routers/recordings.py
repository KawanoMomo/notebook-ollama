from __future__ import annotations

import contextlib
import shutil
import time as _time
from datetime import date
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from apps.api.routers.audio import _resolve_audio_path
from apps.api.schemas.recording import (
    ActiveRecording,
    MarkerCreate,
    RecordingStarted,
    StartRecording,
)
from core.exceptions import AppError
from core.ids import new_id
from core.logging import get_logger
from core.recording.session import RecordingBusyError
from core.storage import notebooks_repo, sources_repo
from core.storage.chunks_repo import delete_chunks_for_source
from core.storage.source_links_repo import set_parent
from core.storage.source_markers_repo import MarkerRecord, insert_markers

log = get_logger("api.recordings")

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

    # 発表モード: presentation_source_id はセッション/ソース作成前に検証する。
    # ここで弾けば後始末(セッション pop・sources 行削除)が不要になり、
    # RecordingBusyError と同種の後始末パターンを増やさずに済む。
    if body.presentation_source_id is not None:
        try:
            parent = sources_repo.get_source(ctx.conn, body.presentation_source_id)
        except AppError as exc:
            raise HTTPException(
                status_code=400, detail="presentation source not found"
            ) from exc
        if parent.notebook_id != notebook_id or parent.kind not in ("pdf", "pptx"):
            raise HTTPException(
                status_code=400,
                detail="presentation source must be a pdf/pptx in the same notebook",
            )

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
    # 発表モード/マーカー用の共有タイムライン基準。live_caption の有無に依存させない
    # (マーカー at_ms とチャンク start_ms が同一 epoch 上に乗ることが spec §11 の要件)。
    sess.extras["epoch"] = _time.perf_counter()
    sess.extras["markers"] = []
    if body.presentation_source_id is not None:
        sess.extras["presentation_source_id"] = body.presentation_source_id

    # --- Live caption wiring (PREVIEW ONLY) -------------------------------
    # Captions produced here are a low-latency preview; the high-accuracy RAG
    # transcript is built later by the offline pipeline. We accumulate caption
    # messages in live_segments for that future offline persistence step.
    import queue as _queue

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

    # 字幕は「モデルがロードでき次第」開始する参照 holder。録音の PCM 取得は
    # このロードを待たずに始まる(2026-07-05 実機FB: 録音開始が遅い)。
    # faster-whisper large-v3 の初回ロードは数GB/数十秒かかるため、
    # start_recording の HTTP 応答がそれに引きずられていた。
    lc_ref: dict[str, Any] = {"mic": None, "sys": None}
    live_active = bool(body.live_caption)  # 予定として ON。実際の起動は非同期

    if body.live_caption:
        import asyncio as _asyncio

        async def _init_live_captions_async() -> None:
            try:
                # モデルロードはブロッキングなのでワーカースレッドへ
                tr = await _asyncio.to_thread(_get_transcriber, request)
                epoch = sess.extras["epoch"]
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
                lc_ref["mic"] = mic_lc
                lc_ref["sys"] = sys_lc
                sess.extras["live_captions"] = [mic_lc, sys_lc]
                push_to_queue({"type": "live_caption_ready"})
            except Exception as exc:
                push_to_queue({
                    "type": "error",
                    "msg": f"live caption init failed: {type(exc).__name__}: {exc}",
                })

        _asyncio.create_task(_init_live_captions_async())

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
        # lc_ref は非同期の字幕初期化タスクが完了した瞬間から None でなくなる。
        # それまでのフレームは字幕には流れないが、録音 WAV には書かれている。
        lc = lc_ref["mic"]
        if lc is not None:
            lc.accept(samples)

    def on_system_chunk(samples):
        if mute_state.is_muted("system"):
            return
        sys_meter(samples)
        lc = lc_ref["sys"]
        if lc is not None:
            lc.accept(samples)

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
        for _lc in (lc_ref.get("mic"), lc_ref.get("sys")):
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
        presentation_source_id=sess.extras.get("presentation_source_id"),
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
    auto_title_enabled: bool | None = None,
) -> None:
    """録音オフラインパイプラインを background task として投入する(stop / retry 共通)。

    mic_audio / system_audio は解決済みの Path | None。少なくとも一方は非 None で
    あること(呼び出し側で検証)。現行 AudioSettings と共有 transcriber/diarizer を
    流用し、source を PARSING にしてから dispatch する。

    auto_title_enabled: None なら設定値 (a.auto_title) をそのまま使う(通常録音・
    retry は従来どおり)。発表モードの stop は確定タイトルを LLM に上書きさせない
    ため False を明示的に渡す。
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
        auto_title_enabled=a.auto_title if auto_title_enabled is None else auto_title_enabled,
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

    # --- 発表モード: マーカー永続化 + 自動リンク + タイトル確定 (spec §6 終了フロー) --
    # dispatch より前に行う — pipeline がページ割当時に source_markers を読むため。
    src_id = sess.extras.get("source_id", "")
    raw_markers = sess.extras.get("markers", [])
    if raw_markers:
        insert_markers(ctx.conn, [
            MarkerRecord(id=new_id(), source_id=src_id,
                         kind=m["kind"], value=m["value"], at_ms=m["at_ms"])
            for m in raw_markers
        ])
    presentation_parent_id = sess.extras.get("presentation_source_id")
    auto_title = ctx.config.audio.auto_title
    if presentation_parent_id:
        # リンク/タイトル確定の失敗で stop 自体を落とさない: 落とすと pipeline が
        # dispatch されず録音が座礁する(録音中に親ソースが削除された場合等)。
        # 失敗時は warning を出して通常録音扱い(auto_title は設定値のまま)で続行。
        try:
            parent = sources_repo.get_source(ctx.conn, presentation_parent_id)
            set_parent(
                ctx.conn, notebook_id=notebook_id,
                parent_source_id=presentation_parent_id, child_source_id=src_id,
                relation="presentation", meta={"presented_at": date.today().isoformat()},
            )
            sources_repo.update_source_title(
                ctx.conn, src_id,
                f"{parent.title or '資料'} 発表 {date.today():%Y-%m-%d}",
            )
            auto_title = False  # 発表タイトルを LLM 推論で上書きさせない
        except Exception:
            log.warning(
                "presentation_finalize_failed",
                source_id=src_id,
                presentation_source_id=presentation_parent_id,
            )

    # --- Dispatch the offline RAG ingestion pipeline as a background task -----
    mic_wav = _resolve_wav(paths.get("mic"))
    system_wav = _resolve_wav(paths.get("system"))

    _dispatch_recording_pipeline(
        request,
        background,
        notebook_id=notebook_id,
        source_id=src_id,
        mic_audio=mic_wav,
        system_audio=system_wav,
        auto_title_enabled=auto_title,
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
    # 二重起動ガード: 遷移中 status は実行中の変換があるとみなして拒否する
    # (起動時リコンシリエーションにより、実行時の遷移中 status は生きている)。
    # 再試行ボタンの連打で同一ソースへ複数パイプラインが走るのを防ぐ。
    if src.status in (
        sources_repo.SourceStatus.PARSING,
        sources_repo.SourceStatus.CHUNKING,
        sources_repo.SourceStatus.EMBEDDING,
    ):
        raise HTTPException(
            status_code=409,
            detail="変換は既に実行中です。停止してから再試行してください。",
        )

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


@router.post("/api/notebooks/{notebook_id}/recordings/{rid}/markers")
async def add_marker(
    request: Request, notebook_id: str, rid: str, body: MarkerCreate
) -> dict:
    """録音タイムラインへの汎用マーカー記録(spec §6)。at_ms はサーバー算出。

    永続化は Task 3 の役割(source_markers への書き込み)。ここでは
    ``sess.extras["markers"]`` に積むだけの in-memory 記録に留める。
    """
    ctx = request.app.state.ctx
    sess = ctx.recordings.get(rid)
    if sess is None or sess.notebook_id != notebook_id:
        raise HTTPException(status_code=404, detail="recording session not found")
    # page マーカーの value は last_page 復元(active 照会)と pipeline のページ割当で
    # int 化されるため、書き込み時点で int() が受理する文字列であることを保証する。
    # isdigit() は '³' 等 int() が拒む Unicode 数字を通すため、int-parse 基準で弾く
    # (下流3層と同一基準。素通りすると pipeline 側の変換が落ちる)。
    if body.kind == "page":
        try:
            int(body.value)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="page marker value must be an integer string",
            ) from None
    at_ms = int((_time.perf_counter() - sess.extras["epoch"]) * 1000)
    sess.extras["markers"].append({"kind": body.kind, "value": body.value, "at_ms": at_ms})
    return {"at_ms": at_ms}


@router.get("/api/notebooks/{notebook_id}/recordings/active")
async def get_active_recording(request: Request, notebook_id: str) -> Response:
    """進行中の録音セッション照会(リロード復帰用、spec §6 中断・異常系)。"""
    ctx = request.app.state.ctx
    rid = ctx.recordings.active_id
    if rid is None:
        return Response(status_code=204)
    sess = ctx.recordings.get(rid)
    if sess is None or sess.notebook_id != notebook_id:
        return Response(status_code=204)
    # last_page は防御的に算出する: 末尾から遡って最初に int 化できる page マーカーを
    # 採用し、無ければ None。書き込み側で 422 弾き済みだが、このエンドポイントは
    # リロード復帰の生命線なので読み取り側でも例外経路を残さない
    # (isdigit は "³" 等 int() が拒む Unicode 数字を通すため、try/except が最終防壁)。
    last_page: int | None = None
    for m in reversed(sess.extras.get("markers", [])):
        if m["kind"] != "page":
            continue
        try:
            last_page = int(m["value"])
        except (ValueError, TypeError):
            continue
        break
    body = ActiveRecording(
        recording_id=sess.id,
        source_id=sess.extras.get("source_id", ""),
        presentation_source_id=sess.extras.get("presentation_source_id"),
        last_page=last_page,
        # マーカー at_ms と同じ epoch 基準。FE(recordingStore.adopt)はこの値から
        # 経過タイマーを再開する。
        elapsed_ms=int((_time.perf_counter() - sess.extras["epoch"]) * 1000),
    )
    return JSONResponse(content=body.model_dump())


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

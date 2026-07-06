"""チャット音声入力の STT エンドポイント(spec 2026-07-05-chat-voice-input-design §5)。

ステートレス: multipart で音声を受け、16kHz mono WAV に正規化し、共有
transcriber で認識してテキストを返すだけ。録音セッションも保存も持たない。
PTT / ハンズフリーのどちらのモードもこの 1 本を使う。
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile

# recordings.py が audio._resolve_audio_path を import するのと同じ
# cross-router 私用 import の前例に倣う。共有キャッシュ(app.state.transcriber)
# を recordings と共用するため、解決ロジックは複製しない。
from apps.api.routers.recordings import _RECORDING_EXTRA_HINT, _get_transcriber

router = APIRouter(prefix="/api/stt", tags=["stt"])

_FFMPEG_HINT = "ffmpeg not found; install ffmpeg and ensure it is on PATH"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # spec §5: 20MB


def _is_wav_16k_mono(path: Path) -> bool:
    """16kHz mono 16bit PCM WAV なら True(ffmpeg 変換をスキップできる)。"""
    try:
        with wave.open(str(path), "rb") as w:
            return (
                w.getnchannels() == 1
                and w.getframerate() == 16000
                and w.getsampwidth() == 2
            )
    except (wave.Error, EOFError, OSError):
        return False


def _to_wav_16k_mono(src: Path, dst: Path) -> None:
    """任意コンテナ(webm/opus, mp4 等)を 16kHz mono WAV へ変換する。"""
    if shutil.which("ffmpeg") is None:
        raise HTTPException(status_code=503, detail=_FFMPEG_HINT)
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(dst),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=422, detail="audio conversion timed out") from exc
    if proc.returncode != 0 or not dst.exists():
        raise HTTPException(status_code=422, detail="audio conversion failed")


def _resolve_transcriber(request: Request):
    """共有 transcriber を解決。recording extra 欠落は 503 に写像する。"""
    try:
        return _get_transcriber(request)
    except (ImportError, ModuleNotFoundError) as exc:
        raise HTTPException(status_code=503, detail=_RECORDING_EXTRA_HINT) from exc


@router.post("/transcribe")
def transcribe(request: Request, file: UploadFile) -> dict:
    # 意図的に sync def: ffmpeg 変換(subprocess.run)と transcribe 推論は
    # 数秒かかる CPU/GPU 処理。async def のまま await すると single-worker
    # uvicorn のイベントループを占有し、SSE や live-caption WS が詰まる。
    # sync def は FastAPI が自動でスレッドプールにオフロードするため、
    # イベントループをブロックしない。共有 Transcriber は _serial_lock で
    # 直列化済みなのでスレッドプール実行でも安全。
    data = file.file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="audio exceeds 20MB limit")

    tr = _resolve_transcriber(request)
    language = request.app.state.ctx.config.audio.language

    with tempfile.TemporaryDirectory(prefix="stt-") as td:
        src = Path(td) / "input.bin"
        src.write_bytes(data)
        if _is_wav_16k_mono(src):
            wav_path = src
        else:
            wav_path = Path(td) / "input16k.wav"
            _to_wav_16k_mono(src, wav_path)

        with wave.open(str(wav_path), "rb") as w:
            duration_ms = int(w.getnframes() * 1000 / w.getframerate())

        segments = tr.transcribe(
            wav_path,
            channel="mic",
            speaker_id="you",
            language=language,
            session_id="stt",
        )

    # faster-whisper のセグメント text は latin 系では先頭に空白を含むため
    # "".join でも語間は保たれる。ja では無空白連結が正しい。
    text = "".join(seg.text for seg in segments).strip()
    return {"text": text, "duration_ms": duration_ms}

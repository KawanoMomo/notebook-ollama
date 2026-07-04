from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from core.exceptions import AppError
from core.recording.audio_export import AudioExportError, mix_audio
from core.storage import sources_repo

router = APIRouter(prefix="/api/notebooks", tags=["audio"])


_RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)")

_MEDIA_TYPE_BY_EXT = {
    ".m4a": "audio/mp4",
    ".opus": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
}

_AUDIO_EXT_PRIORITY = (".m4a", ".opus", ".mp3", ".wav")


def _resolve_audio_path(base: Path, channel: str) -> Path | None:
    """圧縮音声(.m4a/.opus/.mp3)があれば優先、無ければ生 .wav。どれも無ければ None。"""
    for ext in _AUDIO_EXT_PRIORITY:
        p = base / f"{channel}{ext}"
        if p.exists():
            return p
    return None


async def _resolve_mix_path(base: Path) -> Path | None:
    """ミックス音声のパスを解決する。

    - mic / system の片方しか無ければそのチャンネルをそのまま返す(合成不要)。
    - 両方あれば mix.m4a キャッシュを返す。キャッシュが無い、または入力より
      古い場合は ffmpeg (amix) で生成してから返す。
    - どちらも無ければ None。
    """
    mic = _resolve_audio_path(base, "mic")
    system = _resolve_audio_path(base, "system")
    if mic is None and system is None:
        return None
    if mic is None or system is None:
        return mic or system

    dst = base / "mix.m4a"
    try:
        fresh = dst.exists() and dst.stat().st_mtime >= max(
            mic.stat().st_mtime, system.stat().st_mtime
        )
    except OSError:
        fresh = False
    if not fresh:
        try:
            await mix_audio(mic, system, dst)
        except AudioExportError as exc:
            raise HTTPException(
                status_code=500, detail=f"failed to mix audio: {exc}"
            ) from exc
    return dst


@router.get("/{notebook_id}/sources/{source_id}/audio")
async def get_source_audio(
    request: Request, notebook_id: str, source_id: str, channel: str = "mic"
):
    """Stream a recording source's audio with HTTP Range support.

    Serves ``sources_dir/<source_id>/<channel>.{m4a,wav}`` so an HTML5 <audio>
    element can play and seek. channel=mix (合成) / mic (you) / system (others).
    mix は初回リクエスト時に ffmpeg で合成して mix.m4a にキャッシュする。
    """
    if channel not in ("mix", "mic", "system"):
        raise HTTPException(status_code=400, detail="invalid channel")

    ctx = request.app.state.ctx
    try:
        src = sources_repo.get_source(ctx.conn, source_id)
    except AppError as exc:
        raise HTTPException(status_code=404, detail="source not found") from exc
    if src.notebook_id != notebook_id:
        raise HTTPException(status_code=404, detail="source not in notebook")

    base = ctx.config.sources_dir / source_id
    if channel == "mix":
        audio_path = await _resolve_mix_path(base)
    else:
        audio_path = _resolve_audio_path(base, channel)
    if audio_path is None:
        raise HTTPException(status_code=404, detail="audio file not found")

    media_type = _MEDIA_TYPE_BY_EXT.get(audio_path.suffix.lower(), "application/octet-stream")
    file_size = audio_path.stat().st_size

    range_header = request.headers.get("range")
    if range_header:
        m = _RANGE_RE.match(range_header)
        if not m:
            raise HTTPException(status_code=416, detail="invalid Range header")
        start = int(m.group(1))
        end_str = m.group(2)
        end = int(end_str) if end_str else file_size - 1
        if start >= file_size or end >= file_size or start > end:
            raise HTTPException(
                status_code=416,
                detail="requested range not satisfiable",
                headers={"Content-Range": f"bytes */{file_size}"},
            )
        length = end - start + 1

        def _iter():
            with audio_path.open("rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return StreamingResponse(
            _iter(),
            status_code=206,
            media_type=media_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
            },
        )

    # No Range: serve the whole file.
    return FileResponse(
        audio_path,
        media_type=media_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
        },
    )

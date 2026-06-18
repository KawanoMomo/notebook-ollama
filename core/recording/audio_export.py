from __future__ import annotations

import asyncio
from pathlib import Path

_CODEC = {"aac": "aac", "opus": "libopus", "mp3": "libmp3lame"}


class AudioExportError(Exception):
    pass


def build_ffmpeg_cmd(src: Path, dst: Path, *, fmt: str, bitrate_kbps: int) -> list[str]:
    if fmt == "wav":
        return ["ffmpeg", "-y", "-i", str(src), str(dst)]
    codec = _CODEC.get(fmt)
    if codec is None:
        raise AudioExportError(f"unsupported format: {fmt}")
    return ["ffmpeg", "-y", "-i", str(src), "-c:a", codec, "-b:a", f"{bitrate_kbps}k", str(dst)]


async def convert_audio(src: Path, dst: Path, *, fmt: str, bitrate_kbps: int) -> Path:
    cmd = build_ffmpeg_cmd(src, dst, fmt=fmt, bitrate_kbps=bitrate_kbps)
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    # Single stat after the subprocess has finished — not a blocking-IO hazard.
    if proc.returncode != 0 or not dst.exists():  # noqa: ASYNC240
        raise AudioExportError(err.decode("utf-8", "ignore")[-500:])
    return dst


def delete_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()

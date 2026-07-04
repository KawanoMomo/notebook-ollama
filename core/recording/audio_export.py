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


def build_mix_cmd(mic: Path, system: Path, dst: Path) -> list[str]:
    """mic / system 2チャンネルを 1 本に合成する ffmpeg コマンド。

    amix は入力数で音量を平均化するため、volume=2 で会話音量へ戻す
    (両者の同時発話はほぼ無いので、クリップは実用上問題にならない)。
    """
    return [
        "ffmpeg", "-y",
        "-i", str(mic),
        "-i", str(system),
        "-filter_complex", "amix=inputs=2:duration=longest,volume=2",
        "-c:a", "aac", "-b:a", "96k",
        str(dst),
    ]


async def mix_audio(mic: Path, system: Path, dst: Path) -> Path:
    """mic + system をミックスして dst (AAC/.m4a) を生成する。"""
    cmd = build_mix_cmd(mic, system, dst)
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode != 0 or not dst.exists():  # noqa: ASYNC240
        raise AudioExportError(err.decode("utf-8", "ignore")[-500:])
    return dst


def delete_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()


_EXT = {"aac": ".m4a", "opus": ".opus", "mp3": ".mp3", "wav": ".wav"}


def ext_for_format(fmt: str) -> str:
    """保存形式 → ファイル拡張子。未知は .m4a。"""
    return _EXT.get(fmt, ".m4a")

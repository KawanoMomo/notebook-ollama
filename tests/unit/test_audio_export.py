from pathlib import Path

from core.recording.audio_export import build_ffmpeg_cmd


def test_aac_cmd():
    cmd = build_ffmpeg_cmd(Path("mic.wav"), Path("mic.m4a"), fmt="aac", bitrate_kbps=64)
    assert "ffmpeg" in cmd[0]
    assert "-c:a" in cmd and "aac" in cmd
    assert "64k" in cmd
    assert cmd[-1] == "mic.m4a"


def test_opus_codec():
    cmd = build_ffmpeg_cmd(Path("s.wav"), Path("s.opus"), fmt="opus", bitrate_kbps=48)
    assert "libopus" in cmd

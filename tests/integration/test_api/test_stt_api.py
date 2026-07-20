"""POST /api/stt/transcribe の契約テスト(spec §5 バックエンド API)。

fake transcriber を ctx.transcriber_factory で注入する
(tests/integration/test_api/test_recordings_api.py と同じ test hook)。
"""

from __future__ import annotations

import io
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.routers import stt


def _wav_bytes(sample_rate: int = 16000, ms: int = 500) -> bytes:
    """16kHz mono 16bit PCM の無音 WAV バイト列を生成する。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * int(sample_rate * ms / 1000))
    return buf.getvalue()


class FakeTranscriber:
    def __init__(self, texts: list[str]):
        self._texts = texts
        self.calls: list[dict] = []

    def transcribe(self, wav_path, *, channel, speaker_id, language=None, session_id=""):
        self.calls.append(
            {"wav_path": wav_path, "channel": channel, "language": language}
        )
        return [SimpleNamespace(text=t) for t in self._texts]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        yield c


def _post_wav(client, data: bytes):
    return client.post(
        "/api/stt/transcribe",
        files={"file": ("voice.wav", data, "audio/wav")},
    )


def test_transcribe_joins_segments_and_reports_duration(client):
    fake = FakeTranscriber(["こんにちは", "テストです"])
    client.app.state.ctx.transcriber_factory = lambda: fake

    r = _post_wav(client, _wav_bytes(ms=500))

    assert r.status_code == 200
    body = r.json()
    assert body["text"] == "こんにちはテストです"
    assert body["duration_ms"] == 500
    # 16kHz mono WAV はそのまま transcribe に渡る(ffmpeg 変換なし)
    assert fake.calls[0]["channel"] == "mic"
    # 言語はサーバー設定(cfg.audio.language 既定 "ja")
    assert fake.calls[0]["language"] == "ja"


def test_transcribe_empty_segments_returns_empty_text(client):
    client.app.state.ctx.transcriber_factory = lambda: FakeTranscriber([])

    r = _post_wav(client, _wav_bytes(ms=200))

    assert r.status_code == 200
    assert r.json()["text"] == ""


def test_transcribe_rejects_oversize_upload_with_413(client):
    client.app.state.ctx.transcriber_factory = lambda: FakeTranscriber(["x"])

    r = _post_wav(client, b"\x00" * (20 * 1024 * 1024 + 1))

    assert r.status_code == 413


def test_transcribe_returns_503_when_extra_missing(client):
    def _raise():
        raise ImportError("No module named 'faster_whisper'")

    client.app.state.ctx.transcriber_factory = _raise

    r = _post_wav(client, _wav_bytes(ms=200))

    assert r.status_code == 503
    assert "recording" in r.json()["detail"]


def test_transcribe_returns_503_when_ffmpeg_missing(client, monkeypatch):
    """非16kHz入力は ffmpeg 変換分岐(_to_wav_16k_mono)に入る。ffmpeg 不在なら 503。"""
    client.app.state.ctx.transcriber_factory = lambda: FakeTranscriber(["x"])
    monkeypatch.setattr(stt.shutil, "which", lambda name: None)

    r = _post_wav(client, _wav_bytes(sample_rate=8000, ms=200))

    assert r.status_code == 503
    assert "ffmpeg" in r.json()["detail"]


def test_transcribe_returns_422_when_conversion_fails(client, monkeypatch):
    """ffmpeg はあるが変換コマンドが失敗(returncode != 0)したら 422。"""
    client.app.state.ctx.transcriber_factory = lambda: FakeTranscriber(["x"])
    monkeypatch.setattr(stt.shutil, "which", lambda name: "ffmpeg")
    monkeypatch.setattr(
        stt.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=1, stdout=b"", stderr=b"boom"),
    )

    r = _post_wav(client, _wav_bytes(sample_rate=8000, ms=200))

    assert r.status_code == 422


def test_transcribe_converts_non_16k_input(client, monkeypatch):
    """変換が成功した場合、変換後 16kHz WAV が transcriber に渡り duration_ms も
    変換後ファイル基準になることを検証する(_to_wav_16k_mono 分岐の実質カバレッジ)。
    """
    fake = FakeTranscriber(["へんかんできた"])
    client.app.state.ctx.transcriber_factory = lambda: fake

    converted_ms = 750

    def _fake_run(cmd, *, capture_output=True, timeout=None):
        dst = Path(cmd[-1])
        dst.write_bytes(_wav_bytes(sample_rate=16000, ms=converted_ms))
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(stt.shutil, "which", lambda name: "ffmpeg")
    monkeypatch.setattr(stt.subprocess, "run", _fake_run)

    r = _post_wav(client, _wav_bytes(sample_rate=8000, ms=200))

    assert r.status_code == 200
    body = r.json()
    assert body["text"] == "へんかんできた"
    assert body["duration_ms"] == converted_ms
    assert len(fake.calls) == 1
    called_wav_path = Path(fake.calls[0]["wav_path"])
    assert called_wav_path.name == "input16k.wav"

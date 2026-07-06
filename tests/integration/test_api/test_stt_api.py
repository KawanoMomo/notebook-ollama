"""POST /api/stt/transcribe の契約テスト(spec §5 バックエンド API)。

fake transcriber を ctx.transcriber_factory で注入する
(tests/integration/test_api/test_recordings_api.py と同じ test hook)。
"""

from __future__ import annotations

import io
import wave
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


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

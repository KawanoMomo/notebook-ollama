"""RecordingPipeline の同期STT呼び出しがイベントループを阻塞しないこと (issue #11)。

実機では transcriber.transcribe (faster-whisper) が数分単位でブロックし、
変換中は /api/health を含む全APIが無応答になっていた(2026-07-04 実測)。
CPU/GPUバウンド呼び出しはワーカースレッドへオフロードする。
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
from types import SimpleNamespace

import pytest

from core.recording.recording_pipeline import RecordingPipeline, RecordingPipelineDeps
from core.storage import notebooks_repo, sources_repo
from core.storage.database import migrate
from core.storage.sources_repo import SourceStatus


class _SlowTx:
    """実機の whisper 相当の同期ブロッキングを 0.3 秒で模す。"""

    def transcribe(self, wav, *, channel, speaker_id, language="ja", session_id=""):
        time.sleep(0.3)
        return [
            SimpleNamespace(
                start_ms=0, end_ms=1000, speaker_id=speaker_id,
                text=f"hello from {channel}", language="ja",
            )
        ]


class _Diar:
    def diarize(self, wav):
        return []


class _Ollama:
    async def embed(self, *, model, text):
        return [0.1, 0.2]

    async def generate(self, *, model, prompt, options=None):
        return "title"


class _VS:
    def upsert(self, vectors):
        pass


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    migrate(c)
    return c


@pytest.mark.asyncio
async def test_blocking_transcribe_does_not_starve_event_loop(conn, tmp_path):
    nb = notebooks_repo.create_notebook(conn, name="N")
    src = sources_repo.create_source(conn, notebook_id=nb.id, kind="recording")
    wav = tmp_path / "mic.wav"
    wav.write_bytes(b"RIFF" + b"\x00" * 64)

    ticks = 0

    async def _heartbeat():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    hb = asyncio.create_task(_heartbeat())
    try:
        deps = RecordingPipelineDeps(
            conn=conn, vector_store=_VS(), ollama=_Ollama(), embedding_model="m",
        )
        pipe = RecordingPipeline(deps=deps)
        await pipe.run(
            source_id=src.id, notebook_id=nb.id,
            mic_wav=wav, system_wav=None,
            transcriber=_SlowTx(), diarizer=_Diar(), model="llm",
            diarization_enabled=False, name_inference_enabled=False,
            name_threshold=0.7, keep_audio=False, auto_title_enabled=False,
            storage_format="wav",
        )
    finally:
        hb.cancel()

    after = sources_repo.get_source(conn, src.id)
    assert after.status == SourceStatus.READY

    # transcribe の 0.3 秒間もイベントループが回っていればハートビートは
    # 20 回前後刻める(Windows のタイマ粒度を考慮して閾値 10)。
    # ループが阻塞していると transcribe 中は 1 回も刻めず、数回で終わる。
    assert ticks >= 10, f"event loop starved during transcribe (ticks={ticks})"

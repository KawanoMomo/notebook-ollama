"""RecordingPipeline が READY 直前/直後に summary_runner を呼ぶことの確認。

仕様 §5.2: Step 5 として要約生成を追加。3 回失敗のみ error にする(要約自体の
責務は SummaryJob 側、ここでは hook が呼ばれることだけを担保)。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.recording.recording_pipeline import RecordingPipeline, RecordingPipelineDeps
from core.storage import notebooks_repo, sources_repo
from core.storage.database import migrate
from core.storage.sources_repo import SourceStatus


class _Tx:
    def transcribe(self, wav, *, channel, speaker_id, language="ja", session_id=""):
        from types import SimpleNamespace
        return [
            SimpleNamespace(start_ms=0, end_ms=1000, speaker_id=speaker_id,
                            text=f"hello from {channel}", language="ja")
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
async def test_recording_pipeline_calls_summary_runner_on_ready(conn, tmp_path):
    nb = notebooks_repo.create_notebook(conn, name="N")
    src = sources_repo.create_source(conn, notebook_id=nb.id, kind="recording")
    wav = tmp_path / "mic.wav"
    wav.write_bytes(b"RIFF" + b"\x00" * 64)

    called: list[str] = []

    async def _runner(sid: str) -> None:
        called.append(sid)

    deps = RecordingPipelineDeps(
        conn=conn, vector_store=_VS(), ollama=_Ollama(), embedding_model="m",
        summary_runner=_runner,
    )
    pipe = RecordingPipeline(deps=deps)
    await pipe.run(
        source_id=src.id, notebook_id=nb.id,
        mic_wav=wav, system_wav=None,
        transcriber=_Tx(), diarizer=_Diar(), model="llm",
        diarization_enabled=False, name_inference_enabled=False, name_threshold=0.7,
        keep_audio=False, auto_title_enabled=False, storage_format="wav",
    )

    after = sources_repo.get_source(conn, src.id)
    assert after.status == SourceStatus.READY
    assert called == [src.id]


@pytest.mark.asyncio
async def test_recording_pipeline_summary_runner_failure_keeps_ready(conn, tmp_path):
    nb = notebooks_repo.create_notebook(conn, name="N")
    src = sources_repo.create_source(conn, notebook_id=nb.id, kind="recording")
    wav = tmp_path / "mic.wav"
    wav.write_bytes(b"\x00" * 64)

    async def _boom(_sid: str) -> None:
        raise RuntimeError("boom")

    deps = RecordingPipelineDeps(
        conn=conn, vector_store=_VS(), ollama=_Ollama(), embedding_model="m",
        summary_runner=_boom,
    )
    pipe = RecordingPipeline(deps=deps)
    await pipe.run(
        source_id=src.id, notebook_id=nb.id,
        mic_wav=wav, system_wav=None,
        transcriber=_Tx(), diarizer=_Diar(), model="llm",
        diarization_enabled=False, name_inference_enabled=False, name_threshold=0.7,
        keep_audio=False, auto_title_enabled=False, storage_format="wav",
    )

    after = sources_repo.get_source(conn, src.id)
    assert after.status == SourceStatus.READY

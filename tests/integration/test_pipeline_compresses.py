from __future__ import annotations

from pathlib import Path

from core.recording import recording_pipeline as rp_mod
from core.recording.recording_pipeline import RecordingPipeline, RecordingPipelineDeps
from tests.integration.test_recording_pipeline_fake import (
    FakeBroker,
    FakeDiarizer,
    FakeOllama,
    FakeTranscriber,
    FakeVectorStore,
    _conn,
)


def _pipeline(broker):
    return RecordingPipeline(
        deps=RecordingPipelineDeps(
            conn=_conn(), vector_store=FakeVectorStore(), ollama=FakeOllama(),
            embedding_model="bge-m3", broker=broker,
        )
    )


async def test_pipeline_compresses_and_drops_wav(tmp_path: Path, monkeypatch):
    mic = tmp_path / "mic.wav"
    sysw = tmp_path / "system.wav"
    mic.write_bytes(b"RIFFfakewav")
    sysw.write_bytes(b"RIFFfakewav")

    async def fake_convert(src, dst, *, fmt, bitrate_kbps):
        # Test double: tiny synchronous write in a fake that mirrors the real
        # `convert_audio` coroutine signature. No event loop blocking risk in
        # a unit-scale test, so a sync write is acceptable here.
        Path(dst).write_bytes(b"compressed")  # noqa: ASYNC240
        return Path(dst)

    monkeypatch.setattr(rp_mod, "convert_audio", fake_convert)

    broker = FakeBroker()
    pipeline = _pipeline(broker)
    await pipeline.run(
        source_id="src", notebook_id="nb", mic_wav=mic, system_wav=sysw,
        transcriber=FakeTranscriber(), diarizer=FakeDiarizer(),
        model="qwen3", diarization_enabled=False, name_inference_enabled=False,
        name_threshold=0.7, storage_format="aac", storage_bitrate_kbps=64,
        keep_audio=True,
    )

    assert (tmp_path / "mic.m4a").exists()
    assert (tmp_path / "system.m4a").exists()
    assert not mic.exists()
    assert not sysw.exists()
    assert "compress" in [e.get("step") for e in broker.events]


async def test_pipeline_keep_audio_false_deletes_wav(tmp_path: Path, monkeypatch):
    mic = tmp_path / "mic.wav"
    mic.write_bytes(b"RIFFfakewav")

    async def fail_convert(*a, **k):  # should never be called when keep_audio=False
        raise AssertionError("convert_audio must not run when keep_audio=False")

    monkeypatch.setattr(rp_mod, "convert_audio", fail_convert)

    broker = FakeBroker()
    pipeline = _pipeline(broker)
    await pipeline.run(
        source_id="src", notebook_id="nb", mic_wav=mic, system_wav=None,
        transcriber=FakeTranscriber(), diarizer=FakeDiarizer(),
        model="qwen3", diarization_enabled=False, name_inference_enabled=False,
        name_threshold=0.7, storage_format="aac", keep_audio=False,
    )

    assert not mic.exists()
    assert not (tmp_path / "mic.m4a").exists()


async def test_pipeline_compress_failure_keeps_wav(tmp_path: Path, monkeypatch):
    """圧縮失敗時: WAV を残し、status は ready のまま (best-effort)。"""
    mic = tmp_path / "mic.wav"
    mic.write_bytes(b"RIFFfakewav")

    async def boom_convert(*a, **k):
        raise RuntimeError("ffmpeg boom")

    monkeypatch.setattr(rp_mod, "convert_audio", boom_convert)

    broker = FakeBroker()
    deps = RecordingPipelineDeps(
        conn=_conn(), vector_store=FakeVectorStore(), ollama=FakeOllama(),
        embedding_model="bge-m3", broker=broker,
    )
    pipeline = RecordingPipeline(deps=deps)
    await pipeline.run(
        source_id="src", notebook_id="nb", mic_wav=mic, system_wav=None,
        transcriber=FakeTranscriber(), diarizer=FakeDiarizer(),
        model="qwen3", diarization_enabled=False, name_inference_enabled=False,
        name_threshold=0.7, storage_format="aac", keep_audio=True,
    )
    assert mic.exists()  # 圧縮失敗 → WAV 残存
    status = deps.conn.execute(
        "SELECT status FROM sources WHERE id='src'"
    ).fetchone()["status"]
    assert status == "ready"

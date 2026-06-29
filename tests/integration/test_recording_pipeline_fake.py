"""録音オフライン取り込みパイプラインの統合テスト (全依存を fake で注入)。

実モデル / 実音声を一切使わず、注入された transcriber / diarizer / ollama / broker の
fake のみでパイプライン全体 (STT → diarize → name-infer → correct → chunk → embed →
status READY) をユニットテストする。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from core.recording.diarizer import SpeakerSegment
from core.recording.recording_pipeline import RecordingPipeline, RecordingPipelineDeps
from core.recording.transcriber import TranscriptSegment
from core.storage.database import migrate

# --- fakes -----------------------------------------------------------------


class FakeTranscriber:
    """channel ごとに固定の TranscriptSegment 列を返す fake。"""

    def transcribe(self, wav_path, *, channel, speaker_id, language="ja", session_id=""):
        if channel == "mic":
            return [
                TranscriptSegment(
                    id=None, session_id=session_id, channel="mic",
                    start_ms=0, end_ms=1000, speaker_id=speaker_id,
                    text="おはようございます", language="ja",
                ),
                TranscriptSegment(
                    id=None, session_id=session_id, channel="mic",
                    start_ms=4000, end_ms=5000, speaker_id=speaker_id,
                    text="田中さんお願いします", language="ja",
                ),
            ]
        # system channel: two segments from two different speakers (timeline-wise)
        return [
            TranscriptSegment(
                id=None, session_id=session_id, channel="system",
                start_ms=1000, end_ms=2000, speaker_id=speaker_id,
                text="はい田中です", language="ja",
            ),
            TranscriptSegment(
                id=None, session_id=session_id, channel="system",
                start_ms=6000, end_ms=7000, speaker_id=speaker_id,
                text="鈴木でございます", language="ja",
            ),
        ]


class FakeDiarizer:
    """system タイムラインを 2 話者に分割する fake。"""

    def diarize(self, wav_path):
        return [
            SpeakerSegment(speaker_id="spk_000", start_ms=900, end_ms=2100),
            SpeakerSegment(speaker_id="spk_001", start_ms=5900, end_ms=7100),
        ]


class FakeOllama:
    """embed は固定 3 次元ベクトル。generate はプロンプト内容で分岐:
    name-inference ヘッダなら JSON 配列、それ以外 (校正) は番号付きエコー。"""

    def __init__(self):
        self.embed_calls = 0
        self.generate_prompts: list[str] = []

    async def embed(self, *, model, text):
        self.embed_calls += 1
        return [0.1, 0.2, 0.3]

    async def generate(self, *, model, prompt, options=None):
        self.generate_prompts.append(prompt)
        if "実名を推定する" in prompt:
            # 相手1 → 田中 と推定 (高 confidence)。
            return (
                '[{"speaker":"相手1","name":"田中","confidence":0.95,'
                '"evidence":"田中さんお願いしますへの応答"}]'
            )
        # 校正: 「番号. テキスト」を行から抽出してそのままエコー (件数保存)。
        lines = []
        for raw in prompt.splitlines():
            stripped = raw.strip()
            if stripped and stripped[0].isdigit() and "." in stripped:
                num, _, rest = stripped.partition(".")
                if num.isdigit():
                    lines.append(f"{num}. {rest.strip()}")
        return "\n".join(lines)


class FakeBroker:
    def __init__(self):
        self.events: list[dict] = []

    async def publish(self, topic, payload):
        self.events.append({"topic": topic, **payload})


class FakeVectorStore:
    """upsert された ChunkVector を記録する fake。"""

    def __init__(self):
        self.upserts: list = []

    def ensure_collection(self):
        pass

    def upsert(self, vectors):
        self.upserts.extend(list(vectors))


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    migrate(c)
    c.execute("INSERT INTO notebooks(id,name,created_at,updated_at) VALUES('nb','n','t','t')")
    c.execute(
        "INSERT INTO sources(id,notebook_id,kind,status,created_at,updated_at) "
        "VALUES('src','nb','recording','pending','t','t')"
    )
    return c


# --- tests -----------------------------------------------------------------


async def test_recording_pipeline_end_to_end(tmp_path: Path):
    conn = _conn()
    vs = FakeVectorStore()
    ollama = FakeOllama()
    broker = FakeBroker()

    pipeline = RecordingPipeline(
        deps=RecordingPipelineDeps(
            conn=conn, vector_store=vs, ollama=ollama,
            embedding_model="bge-m3", broker=broker,
        )
    )

    await pipeline.run(
        source_id="src", notebook_id="nb",
        mic_wav=tmp_path / "mic.wav", system_wav=tmp_path / "system.wav",
        transcriber=FakeTranscriber(), diarizer=FakeDiarizer(),
        model="qwen3", diarization_enabled=True, name_inference_enabled=True,
        name_threshold=0.7, max_tokens=400,
    )

    # 1. chunks inserted with non-null timecode + speaker
    rows = conn.execute(
        "SELECT ord, text, start_ms, end_ms, speaker FROM chunks "
        "WHERE source_id='src' ORDER BY ord"
    ).fetchall()
    assert rows, "no chunks inserted"
    for r in rows:
        assert r["start_ms"] is not None
        assert r["end_ms"] is not None
        assert r["speaker"] is not None

    # 2. vector store received upserts with start_ms/speaker/channel
    assert vs.upserts, "no vectors upserted"
    assert len(vs.upserts) == len(rows)
    for v in vs.upserts:
        assert v.start_ms is not None
        assert v.speaker is not None
        assert v.channel in ("mic", "system")
        assert v.source_kind == "recording"

    # mic chunks → channel mic; system chunks → channel system
    by_speaker = {v.speaker: v for v in vs.upserts}
    assert by_speaker["あなた"].channel == "mic"
    for v in vs.upserts:
        if v.speaker != "あなた":
            assert v.channel == "system"

    # 3. source status == ready
    status = conn.execute("SELECT status FROM sources WHERE id='src'").fetchone()["status"]
    assert status == "ready"

    # 4. broker received multiple step events
    steps = [e.get("step") for e in broker.events if e.get("step")]
    assert "transcribe" in steps
    assert "diarize" in steps
    assert "correct" in steps
    assert "chunk" in steps
    assert "embed" in steps
    assert len(broker.events) >= 5

    # 5. name inference: 相手1 → 田中, channel stays system
    speakers = {v.speaker for v in vs.upserts}
    assert "田中" in speakers, f"name inference not applied; got {speakers}"
    assert by_speaker.get("田中") and by_speaker["田中"].channel == "system"
    # the inferred-name chunk must NOT be 相手1 anymore
    assert "相手1" not in speakers


async def test_recording_pipeline_no_diarization_no_name_infer(tmp_path: Path):
    """diarization / name-inference 無効時: system 話者は全て '相手'。"""
    conn = _conn()
    vs = FakeVectorStore()
    ollama = FakeOllama()
    broker = FakeBroker()

    pipeline = RecordingPipeline(
        deps=RecordingPipelineDeps(
            conn=conn, vector_store=vs, ollama=ollama,
            embedding_model="bge-m3", broker=broker,
        )
    )

    await pipeline.run(
        source_id="src", notebook_id="nb",
        mic_wav=tmp_path / "mic.wav", system_wav=tmp_path / "system.wav",
        transcriber=FakeTranscriber(), diarizer=FakeDiarizer(),
        model="qwen3", diarization_enabled=False, name_inference_enabled=False,
        name_threshold=0.7,
    )

    status = conn.execute("SELECT status FROM sources WHERE id='src'").fetchone()["status"]
    assert status == "ready"
    speakers = {v.speaker for v in vs.upserts}
    assert speakers == {"あなた", "相手"}
    for v in vs.upserts:
        if v.speaker == "あなた":
            assert v.channel == "mic"
        else:
            assert v.channel == "system"
    # name inference disabled → no name-inference generate call
    assert not any("実名を推定する" in p for p in ollama.generate_prompts)


async def test_recording_pipeline_mic_only(tmp_path: Path):
    """system_wav が無い (None) 場合: mic のみで成立。"""
    conn = _conn()
    vs = FakeVectorStore()
    pipeline = RecordingPipeline(
        deps=RecordingPipelineDeps(
            conn=conn, vector_store=vs, ollama=FakeOllama(),
            embedding_model="bge-m3", broker=None,
        )
    )
    await pipeline.run(
        source_id="src", notebook_id="nb",
        mic_wav=tmp_path / "mic.wav", system_wav=None,
        transcriber=FakeTranscriber(), diarizer=FakeDiarizer(),
        model="qwen3", diarization_enabled=True, name_inference_enabled=True,
        name_threshold=0.7,
    )
    status = conn.execute("SELECT status FROM sources WHERE id='src'").fetchone()["status"]
    assert status == "ready"
    speakers = {v.speaker for v in vs.upserts}
    assert speakers == {"あなた"}
    for v in vs.upserts:
        assert v.channel == "mic"


async def test_recording_pipeline_marks_error_on_failure(tmp_path: Path):
    """途中で例外が出たら status=error にして握りつぶす (background task)。"""
    conn = _conn()
    vs = FakeVectorStore()
    broker = FakeBroker()

    class BoomTranscriber:
        def transcribe(self, *a, **k):
            raise RuntimeError("boom-stt")

    pipeline = RecordingPipeline(
        deps=RecordingPipelineDeps(
            conn=conn, vector_store=vs, ollama=FakeOllama(),
            embedding_model="bge-m3", broker=broker,
        )
    )
    # must not raise
    await pipeline.run(
        source_id="src", notebook_id="nb",
        mic_wav=tmp_path / "mic.wav", system_wav=None,
        transcriber=BoomTranscriber(), diarizer=FakeDiarizer(),
        model="qwen3", diarization_enabled=False, name_inference_enabled=False,
        name_threshold=0.7,
    )
    row = conn.execute("SELECT status, error_msg FROM sources WHERE id='src'").fetchone()
    assert row["status"] == "error"
    assert row["error_msg"] and "boom-stt" in row["error_msg"]
    assert any(e.get("status") == "error" for e in broker.events)

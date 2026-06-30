"""auto_title_enabled の挙動を検証する統合テスト(全依存 fake)。

- auto_title ON かつ corrected セグメントあり → source.title が設定される。
- auto_title OFF → title は不変(None のまま)。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from core.recording.recording_pipeline import RecordingPipeline, RecordingPipelineDeps
from core.recording.transcriber import TranscriptSegment
from core.storage import sources_repo
from core.storage.database import migrate


class FakeTranscriber:
    def transcribe(self, wav_path, *, channel, speaker_id, language="ja", session_id=""):
        if channel == "mic":
            return [
                TranscriptSegment(
                    id=None, session_id=session_id, channel="mic",
                    start_ms=0, end_ms=1000, speaker_id=speaker_id,
                    text="来期の予算を見直したい", language="ja",
                ),
            ]
        return []


class FakeOllama:
    """title プロンプトには固定タイトル、name-inference には空配列、
    校正には番号付きエコーを返す。"""

    async def embed(self, *, model, text):
        return [0.1, 0.2, 0.3]

    async def generate(self, *, model, prompt, options=None):
        if "簡潔なタイトル" in prompt:
            return "「来期予算レビュー」"
        if "実名を推定する" in prompt:
            return "[]"
        lines = []
        for raw in prompt.splitlines():
            stripped = raw.strip()
            if stripped and stripped[0].isdigit() and "." in stripped:
                num, _, rest = stripped.partition(".")
                if num.isdigit():
                    lines.append(f"{num}. {rest.strip()}")
        return "\n".join(lines)


class FakeVectorStore:
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
        "INSERT INTO sources(id,notebook_id,kind,title,status,created_at,updated_at) "
        "VALUES('src','nb','recording',NULL,'pending','t','t')"
    )
    return c


def _pipeline(conn):
    return RecordingPipeline(
        deps=RecordingPipelineDeps(
            conn=conn, vector_store=FakeVectorStore(), ollama=FakeOllama(),
            embedding_model="bge-m3", broker=None,
        )
    )


async def test_auto_title_on_sets_source_title(tmp_path: Path):
    conn = _conn()
    await _pipeline(conn).run(
        source_id="src", notebook_id="nb",
        mic_wav=tmp_path / "mic.wav", system_wav=None,
        transcriber=FakeTranscriber(), diarizer=None,
        model="qwen3", diarization_enabled=False, name_inference_enabled=False,
        name_threshold=0.7, auto_title_enabled=True,
    )
    src = sources_repo.get_source(conn, "src")
    assert src.status is sources_repo.SourceStatus.READY
    assert src.title == "来期予算レビュー"


async def test_auto_title_off_keeps_title_none(tmp_path: Path):
    conn = _conn()
    await _pipeline(conn).run(
        source_id="src", notebook_id="nb",
        mic_wav=tmp_path / "mic.wav", system_wav=None,
        transcriber=FakeTranscriber(), diarizer=None,
        model="qwen3", diarization_enabled=False, name_inference_enabled=False,
        name_threshold=0.7, auto_title_enabled=False,
    )
    src = sources_repo.get_source(conn, "src")
    assert src.status is sources_repo.SourceStatus.READY
    assert src.title is None

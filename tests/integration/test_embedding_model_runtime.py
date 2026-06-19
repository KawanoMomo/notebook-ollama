"""embedding_model のサービス実行時参照テスト。

build_context で渡した getter が config.ollama.embedding_model の実行時変更を
反映し、再起動なしで pipeline / retrieval / recording_pipeline が新しい
埋め込みモデル名で embed() を呼ぶことを確認する。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from apps.api.dependencies import build_context
from core.config import AppConfig
from core.ingestion.pipeline import IngestionPipeline, PipelineDeps
from core.recording.recording_pipeline import RecordingPipeline, RecordingPipelineDeps
from core.retrieval.search import RetrievalService
from core.storage.chunks_repo import ChunkRecord, insert_chunks
from core.storage.database import connect, migrate
from core.storage.notebooks_repo import create_notebook
from core.storage.sources_repo import SourceStatus, create_source, get_source
from core.storage.vector_store import ChunkVector, VectorStore


class RecordingFakeGateway:
    """embed の model 名を記録。generate は校正/名前推定をスキップさせる無害な応答。"""

    def __init__(self) -> None:
        self.embed_models: list[str] = []

    async def embed(self, *, model: str, text: str) -> list[float]:
        self.embed_models.append(model)
        return [0.1, 0.2, 0.3, 0.4]

    async def generate(self, *, model, prompt, options=None) -> str:
        return ""


class FakeGateway:
    def __init__(self) -> None:
        self.embed_models: list[str] = []

    async def embed(self, *, model: str, text: str) -> list[float]:
        self.embed_models.append(model)
        return [1.0, 0.0, 0.0, 0.0]


class FakeVectorStore:
    def __init__(self) -> None:
        self.upserts: list = []

    def ensure_collection(self) -> None:
        pass

    def upsert(self, vectors) -> None:
        self.upserts.extend(list(vectors))


class FakeTranscriber:
    def transcribe(self, wav_path, *, channel, speaker_id, language="ja", session_id=""):
        from core.recording.transcriber import TranscriptSegment

        return [
            TranscriptSegment(
                id=None, session_id=session_id, channel="mic",
                start_ms=0, end_ms=1000, speaker_id=speaker_id,
                text="こんにちは", language="ja",
            )
        ]


class FakeDiarizer:
    def diarize(self, wav_path):
        return []


def _rec_conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    migrate(c)
    c.execute("INSERT INTO notebooks(id,name,created_at,updated_at) VALUES('nb','n','t','t')")
    c.execute(
        "INSERT INTO sources(id,notebook_id,kind,status,created_at,updated_at) "
        "VALUES('src','nb','recording','pending','t','t')"
    )
    return c


@pytest.mark.asyncio
async def test_retrieval_uses_getter_at_runtime(tmp_path):
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    src = create_source(conn, notebook_id=nb.id, kind="md", title="Doc", content_hash="h")
    insert_chunks(
        conn,
        [
            ChunkRecord(
                id="a" * 26, source_id=src.id, notebook_id=nb.id, ord=0,
                page=None, heading_path=None, text="hello", token_count=1,
            )
        ],
    )
    vs = VectorStore(path=tmp_path / "q", dim=4)
    vs.ensure_collection()
    vs.upsert(
        [
            ChunkVector(
                id="a" * 26, vector=[1, 0, 0, 0], notebook_id=nb.id,
                source_id=src.id, source_kind="md", page=None,
                heading_path=None, ord=0,
            )
        ]
    )
    gw = FakeGateway()
    current = {"model": "bge-m3"}
    svc = RetrievalService(
        conn=conn, vector_store=vs, ollama=gw,
        embedding_model="bge-m3",
        embedding_model_getter=lambda: current["model"],
    )
    await svc.search(notebook_id=nb.id, query="hi", limit=5)
    assert gw.embed_models[-1] == "bge-m3"
    # 実行時に cfg 相当を変更 → 再起動なしで反映される
    current["model"] = "nomic-embed-text"
    await svc.search(notebook_id=nb.id, query="hi", limit=5)
    assert gw.embed_models[-1] == "nomic-embed-text"


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_pipeline_uses_getter_at_runtime(tmp_path):
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    vs = VectorStore(path=tmp_path / "q", dim=4)
    vs.ensure_collection()
    gw = FakeGateway()
    current = {"model": "bge-m3"}
    pipeline = IngestionPipeline(
        deps=PipelineDeps(
            conn=conn, vector_store=vs, ollama=gw,
            embedding_model="bge-m3",
            embedding_model_getter=lambda: current["model"],
        )
    )
    src1 = create_source(conn, notebook_id=nb.id, kind="markdown", origin="a.md", content_hash="h1")
    await pipeline.run(source_id=src1.id, kind="markdown", data=b"# T\n\nbody one.\n")
    assert get_source(conn, src1.id).status == SourceStatus.READY
    assert gw.embed_models and all(m == "bge-m3" for m in gw.embed_models)

    current["model"] = "mxbai-embed-large"
    src2 = create_source(conn, notebook_id=nb.id, kind="markdown", origin="b.md", content_hash="h2")
    await pipeline.run(source_id=src2.id, kind="markdown", data=b"# T2\n\nbody two.\n")
    assert gw.embed_models[-1] == "mxbai-embed-large"


@pytest.mark.asyncio
async def test_recording_pipeline_uses_getter_at_runtime(tmp_path: Path):
    conn = _rec_conn()
    vs = FakeVectorStore()
    gw = RecordingFakeGateway()
    current = {"model": "bge-m3"}
    pipeline = RecordingPipeline(
        deps=RecordingPipelineDeps(
            conn=conn, vector_store=vs, ollama=gw,
            embedding_model="bge-m3",
            embedding_model_getter=lambda: current["model"],
            broker=None,
        )
    )
    current["model"] = "snowflake-arctic-embed"
    await pipeline.run(
        source_id="src", notebook_id="nb",
        mic_wav=tmp_path / "mic.wav", system_wav=None,
        transcriber=FakeTranscriber(), diarizer=FakeDiarizer(),
        model="qwen3", diarization_enabled=False, name_inference_enabled=False,
        name_threshold=0.7,
    )
    status = conn.execute("SELECT status FROM sources WHERE id='src'").fetchone()["status"]
    assert status == "ready"
    assert gw.embed_models, "embed が呼ばれていない"
    assert all(m == "snowflake-arctic-embed" for m in gw.embed_models)


def test_build_context_wires_embedding_getter(tmp_path):
    cfg = AppConfig(data_dir=tmp_path)
    cfg.ollama = cfg.ollama.model_copy(update={"embedding_model": "bge-m3"})
    ctx = build_context(cfg)
    # getter は build_context で配線され、cfg.ollama 差し替えを反映する
    assert ctx.pipeline._deps.embedding_model_getter is not None
    assert ctx.pipeline._deps.embedding_model_getter() == "bge-m3"
    assert ctx.recording_pipeline._deps.embedding_model_getter() == "bge-m3"
    ctx.config.ollama = ctx.config.ollama.model_copy(update={"embedding_model": "nomic-embed-text"})
    assert ctx.pipeline._deps.embedding_model_getter() == "nomic-embed-text"
    assert ctx.recording_pipeline._deps.embedding_model_getter() == "nomic-embed-text"

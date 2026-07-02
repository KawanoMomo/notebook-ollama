"""IngestionPipeline / RecordingPipeline が EmbeddingJob 完了後に
summary_runner を呼ぶことの単体確認。

仕様: §5.1 (ドキュメント) / §5.2 (録音)
"""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_ingestion_pipeline_invokes_summary_runner_after_ready(tmp_path):
    """ドキュメント取込が READY に達した直後に summary_runner(source_id) が呼ばれる。"""
    import sqlite3

    from core.ingestion.pipeline import IngestionPipeline, PipelineDeps
    from core.storage import notebooks_repo
    from core.storage.database import migrate

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    migrate(conn)
    nb = notebooks_repo.create_notebook(conn, name="N")

    class _FakeOllama:
        async def embed(self, *, model: str, text: str) -> list[float]:
            return [0.1, 0.2, 0.3]

    class _FakeVS:
        def upsert(self, vectors):
            pass

    md = b"# Title\n\nhello world hello world hello world hello world hello world."
    from core.storage.sources_repo import SourceStatus, create_source
    src = create_source(conn, notebook_id=nb.id, kind="markdown", origin="t.md")

    summary_calls: list[str] = []

    async def _summary_runner(source_id: str) -> None:
        summary_calls.append(source_id)

    pipeline = IngestionPipeline(
        deps=PipelineDeps(
            conn=conn,
            vector_store=_FakeVS(),
            ollama=_FakeOllama(),
            embedding_model="m",
            summary_runner=_summary_runner,
        )
    )
    await pipeline.run(source_id=src.id, kind="markdown", data=md)

    from core.storage.sources_repo import get_source
    assert get_source(conn, src.id).status == SourceStatus.READY
    assert summary_calls == [src.id]


@pytest.mark.asyncio
async def test_ingestion_pipeline_summary_runner_failure_does_not_fail_ingestion(tmp_path):
    """summary_runner が例外を投げても source.status は READY を維持する。

    要約は best-effort: 失敗はソースの READY 化を阻害しない。
    """
    import sqlite3

    from core.ingestion.pipeline import IngestionPipeline, PipelineDeps
    from core.storage import notebooks_repo
    from core.storage.database import migrate
    from core.storage.sources_repo import SourceStatus, create_source, get_source

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    migrate(conn)
    nb = notebooks_repo.create_notebook(conn, name="N")
    src = create_source(conn, notebook_id=nb.id, kind="markdown", origin="t.md")

    class _FakeOllama:
        async def embed(self, *, model: str, text: str) -> list[float]:
            return [0.1]

    class _FakeVS:
        def upsert(self, vectors):
            pass

    async def _boom(_sid: str) -> None:
        raise RuntimeError("summary runner crashed")

    pipeline = IngestionPipeline(
        deps=PipelineDeps(
            conn=conn,
            vector_store=_FakeVS(),
            ollama=_FakeOllama(),
            embedding_model="m",
            summary_runner=_boom,
        )
    )
    await pipeline.run(
        source_id=src.id,
        kind="markdown",
        data=b"# Title\n\nbody text body text body text body text.",
    )

    # READY のまま(要約失敗はソース取込の失敗にしない)
    assert get_source(conn, src.id).status == SourceStatus.READY

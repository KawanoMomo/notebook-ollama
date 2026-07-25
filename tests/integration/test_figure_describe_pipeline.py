from __future__ import annotations

import pytest

pymupdf = pytest.importorskip("pymupdf")
pytestmark = pytest.mark.pdf

from core.ingestion.pipeline import IngestionPipeline, PipelineDeps  # noqa: E402
from core.storage.assets_repo import list_assets_for_source  # noqa: E402
from core.storage.chunks_repo import list_chunks_for_source  # noqa: E402
from core.storage.database import connect, migrate  # noqa: E402
from core.storage.notebooks_repo import create_notebook  # noqa: E402
from core.storage.sources_repo import SourceStatus, create_source, get_source  # noqa: E402
from core.storage.vector_store import VectorStore  # noqa: E402
from tests.unit.fixtures_pdf import build_pdf_with_image  # noqa: E402


class FakeGateway:
    async def embed(self, *, model: str, text: str) -> list[float]:
        return [float(len(text)), 0.0, 0.0, 0.0]


class FakeDescriber:
    def __init__(self, text: str | None = "図の説明: サンプル画像です。"):
        self._text = text
        self.calls = 0

    async def describe(self, *, image_png: bytes) -> str | None:
        self.calls += 1
        return self._text


def _setup(tmp_path):
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    src = create_source(conn, notebook_id=nb.id, kind="pdf", origin="t.pdf", content_hash="h")
    vs = VectorStore(path=tmp_path / "qdrant", dim=4)
    vs.ensure_collection()
    return conn, src, vs


def _pipeline(conn, vs, *, assets_dir, describer, describe_enabled):
    return IngestionPipeline(
        deps=PipelineDeps(
            conn=conn,
            vector_store=vs,
            ollama=FakeGateway(),
            embedding_model="bge-m3",
            assets_dir=assets_dir,
            assets_enabled=lambda: True,
            figure_describer=describer,
            figure_describe_enabled=describe_enabled,
        )
    )


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_figure_gets_described_and_creates_independent_chunk(tmp_path):
    conn, src, vs = _setup(tmp_path)
    describer = FakeDescriber("これは配置図です。")
    pipeline = _pipeline(
        conn, vs, assets_dir=tmp_path / "assets", describer=describer,
        describe_enabled=lambda: True,
    )

    await pipeline.run(source_id=src.id, kind="pdf", data=build_pdf_with_image())

    assert get_source(conn, src.id).status == SourceStatus.READY
    assert describer.calls == 1

    chunks = list_chunks_for_source(conn, src.id)
    desc_chunks = [c for c in chunks if c.kind == "figure_desc"]
    assert len(desc_chunks) == 1
    assert desc_chunks[0].text == "これは配置図です。"

    assets = list_assets_for_source(conn, src.id)
    fig = next(a for a in assets if a.kind == "figure")
    assert fig.desc_chunk_id == desc_chunks[0].id


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_describe_disabled_creates_no_figure_desc_chunk(tmp_path):
    conn, src, vs = _setup(tmp_path)
    describer = FakeDescriber("使われないはず")
    pipeline = _pipeline(
        conn, vs, assets_dir=tmp_path / "assets", describer=describer,
        describe_enabled=lambda: False,
    )
    await pipeline.run(source_id=src.id, kind="pdf", data=build_pdf_with_image())
    assert get_source(conn, src.id).status == SourceStatus.READY
    assert describer.calls == 0
    chunks = list_chunks_for_source(conn, src.id)
    assert not [c for c in chunks if c.kind == "figure_desc"]


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_describe_failure_is_graceful_and_does_not_fail_ingestion(tmp_path):
    conn, src, vs = _setup(tmp_path)
    describer = FakeDescriber(None)  # 常に説明失敗
    pipeline = _pipeline(
        conn, vs, assets_dir=tmp_path / "assets", describer=describer,
        describe_enabled=lambda: True,
    )
    await pipeline.run(source_id=src.id, kind="pdf", data=build_pdf_with_image())
    assert get_source(conn, src.id).status == SourceStatus.READY
    chunks = list_chunks_for_source(conn, src.id)
    assert not [c for c in chunks if c.kind == "figure_desc"]
    # 図アセット自体は残る(未解析のまま、後で「図を解析」で再試行可能)
    assets = list_assets_for_source(conn, src.id)
    fig = next(a for a in assets if a.kind == "figure")
    assert fig.desc_chunk_id is None

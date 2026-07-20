"""Task 8: IngestionPipeline のアセット保存・chunk 紐付け・グレースフルデグレード。

API レベル(ベータゲート・reingest ディスパッチ・共通クリーンアップ)は
tests/integration/test_api/test_source_reingest_assets_api.py を参照。
"""
from __future__ import annotations

import pytest

pymupdf = pytest.importorskip("pymupdf")
pytestmark = pytest.mark.pdf

from tests.unit.fixtures_pdf import build_pdf_with_image, build_pdf_with_table  # noqa: E402

from core.ingestion.pipeline import IngestionPipeline, PipelineDeps  # noqa: E402
from core.storage.assets_repo import list_assets_for_source  # noqa: E402
from core.storage.chunks_repo import get_chunks_by_ids  # noqa: E402
from core.storage.database import connect, migrate  # noqa: E402
from core.storage.notebooks_repo import create_notebook  # noqa: E402
from core.storage.sources_repo import SourceStatus, create_source, get_source  # noqa: E402
from core.storage.vector_store import VectorStore  # noqa: E402

ROWS = [["品名", "数量"], ["ネジ", "10"]]


class FakeGateway:
    async def embed(self, *, model: str, text: str) -> list[float]:
        return [float(len(text)), 0.0, 0.0, 0.0]


def _setup(tmp_path):
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    src = create_source(conn, notebook_id=nb.id, kind="pdf", origin="t.pdf", content_hash="h")
    vs = VectorStore(path=tmp_path / "qdrant", dim=4)
    vs.ensure_collection()
    return conn, src, vs


def _pipeline(conn, vs, *, assets_dir, assets_enabled):
    return IngestionPipeline(
        deps=PipelineDeps(
            conn=conn,
            vector_store=vs,
            ollama=FakeGateway(),
            embedding_model="bge-m3",
            assets_dir=assets_dir,
            assets_enabled=assets_enabled,
        )
    )


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_table_asset_saved_and_linked_to_chunk_when_enabled(tmp_path):
    conn, src, vs = _setup(tmp_path)
    pipeline = _pipeline(conn, vs, assets_dir=tmp_path / "assets", assets_enabled=lambda: True)

    await pipeline.run(source_id=src.id, kind="pdf", data=build_pdf_with_table(ROWS))

    assert get_source(conn, src.id).status == SourceStatus.READY
    assets = list_assets_for_source(conn, src.id)
    tables = [a for a in assets if a.kind == "table"]
    assert len(tables) == 1
    linked = get_chunks_by_ids(conn, [tables[0].chunk_id])
    assert linked and tables[0].md_snippet in linked[0].text


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_figure_asset_saved_as_png_and_linked_to_page_first_chunk(tmp_path):
    conn, src, vs = _setup(tmp_path)
    assets_dir = tmp_path / "assets"
    pipeline = _pipeline(conn, vs, assets_dir=assets_dir, assets_enabled=lambda: True)

    await pipeline.run(source_id=src.id, kind="pdf", data=build_pdf_with_image())

    assert get_source(conn, src.id).status == SourceStatus.READY
    assets = list_assets_for_source(conn, src.id)
    figs = [a for a in assets if a.kind == "figure"]
    assert len(figs) == 1
    assert figs[0].chunk_id
    png_path = assets_dir / src.id / f"{figs[0].id}.png"
    assert png_path.exists()
    assert png_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_no_assets_saved_when_disabled(tmp_path):
    conn, src, vs = _setup(tmp_path)
    pipeline = _pipeline(conn, vs, assets_dir=tmp_path / "assets", assets_enabled=lambda: False)

    await pipeline.run(source_id=src.id, kind="pdf", data=build_pdf_with_table(ROWS))

    assert get_source(conn, src.id).status == SourceStatus.READY
    assert list_assets_for_source(conn, src.id) == []


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_no_assets_extracted_when_assets_dir_missing(tmp_path):
    """assets_enabled=True でも assets_dir 未設定なら抽出自体を行わない(未配線環境の安全側)。"""
    conn, src, vs = _setup(tmp_path)
    pipeline = _pipeline(conn, vs, assets_dir=None, assets_enabled=lambda: True)

    await pipeline.run(source_id=src.id, kind="pdf", data=build_pdf_with_table(ROWS))

    assert get_source(conn, src.id).status == SourceStatus.READY
    assert list_assets_for_source(conn, src.id) == []


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_asset_save_failure_does_not_fail_ingestion(tmp_path, monkeypatch):
    conn, src, vs = _setup(tmp_path)
    pipeline = _pipeline(conn, vs, assets_dir=tmp_path / "assets", assets_enabled=lambda: True)

    import core.ingestion.pipeline as pipeline_mod

    def _boom(conn, assets):
        raise RuntimeError("disk full")

    monkeypatch.setattr(pipeline_mod, "insert_assets", _boom)

    await pipeline.run(source_id=src.id, kind="pdf", data=build_pdf_with_table(ROWS))

    # アセット保存が失敗しても取込全体は READY まで進む
    assert get_source(conn, src.id).status == SourceStatus.READY
    assert list_assets_for_source(conn, src.id) == []


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_non_pdf_kind_never_extracts_assets(tmp_path):
    """assets_enabled=True でも kind!='pdf' なら extract_assets は渡らない(markdown 等は対象外)。"""
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    src = create_source(conn, notebook_id=nb.id, kind="markdown", origin="x.md", content_hash="h")
    vs = VectorStore(path=tmp_path / "qdrant", dim=4)
    vs.ensure_collection()
    pipeline = _pipeline(conn, vs, assets_dir=tmp_path / "assets", assets_enabled=lambda: True)

    await pipeline.run(
        source_id=src.id, kind="markdown", data=b"# Title\n\nSome content here.\n"
    )

    assert get_source(conn, src.id).status == SourceStatus.READY
    assert list_assets_for_source(conn, src.id) == []

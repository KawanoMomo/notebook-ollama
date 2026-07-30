import pytest

pymupdf = pytest.importorskip("pymupdf")
pytestmark = [pytest.mark.pdf, pytest.mark.qdrant]

from core.storage.database import connect, migrate  # noqa: E402
from core.storage.notebooks_repo import create_notebook  # noqa: E402
from core.storage.sources_repo import (  # noqa: E402
    SourceStatus,
    create_source,
    update_source_status,
)
from core.storage.vector_store import VectorStore  # noqa: E402
from core.storage.visual_index_repo import get_meta, list_indexed_source_ids  # noqa: E402
from core.storage.visual_store import VisualPageStore, VisualUnitStore  # noqa: E402
from core.visual.index_builder import BuilderDeps, VisualIndexBuilder  # noqa: E402


class FakeEncoder:
    def __init__(self, fail_on_call: int | None = None):
        self.calls = 0
        self._fail_on = fail_on_call

    async def embed_image(self, *, png: bytes) -> list[float]:
        self.calls += 1
        if self._fail_on is not None and self.calls == self._fail_on:
            raise RuntimeError("embed boom")
        return [float(self.calls), 1.0, 0.0, 0.0]

    async def embed_text(self, *, text: str) -> list[float]:
        return [1.0, 0.0, 0.0, 0.0]

    def unload(self) -> None:
        pass


def _two_page_pdf() -> bytes:
    doc = pymupdf.open()
    for i in range(2):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), f"page {i + 1}", fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def _setup(tmp_path):
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    vs = VectorStore(path=tmp_path / "q", dim=4)
    vs.ensure_collection()
    ps = VisualPageStore(client=vs.client)
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    assets_dir = tmp_path / "assets"
    return conn, nb, ps, sources_dir, assets_dir


def _add_pdf_source(conn, nb, sources_dir, *, sid_hint="h1") -> str:
    src = create_source(conn, notebook_id=nb.id, kind="pdf", origin="t.pdf", content_hash=sid_hint)
    (sources_dir / f"{src.id}.pdf").write_bytes(_two_page_pdf())
    update_source_status(conn, src.id, status=SourceStatus.READY)
    return src.id


async def test_build_indexes_pages_and_saves_pngs(tmp_path):
    conn, nb, ps, sources_dir, assets_dir = _setup(tmp_path)
    sid = _add_pdf_source(conn, nb, sources_dir)
    progress_log = []

    async def progress(done, total):
        progress_log.append((done, total))

    builder = VisualIndexBuilder(deps=BuilderDeps(
        conn=conn, visual_store=ps, encoder=FakeEncoder(),
        sources_dir=sources_dir, assets_dir=assets_dir,
        embedding_model_name="test-model", progress=progress,
    ))
    result = await builder.build(nb.id)

    assert result.indexed_pages == 2 and result.indexed_sources == 1
    assert get_meta(conn, nb.id).embedding_model == "test-model"
    assert list_indexed_source_ids(conn, nb.id) == {sid}
    assert (assets_dir / sid / "pages" / "1.png").exists()
    assert (assets_dir / sid / "pages" / "2.png").exists()
    hits = ps.search(query=[1.0, 1.0, 0.0, 0.0], notebook_id=nb.id, limit=5)
    assert len(hits) == 2
    assert progress_log[-1] == (2, 2)


async def test_incremental_build_skips_indexed_sources(tmp_path):
    conn, nb, ps, sources_dir, assets_dir = _setup(tmp_path)
    _add_pdf_source(conn, nb, sources_dir, sid_hint="h1")
    enc = FakeEncoder()
    deps = BuilderDeps(
        conn=conn, visual_store=ps, encoder=enc, sources_dir=sources_dir,
        assets_dir=assets_dir, embedding_model_name="test-model",
    )
    await VisualIndexBuilder(deps=deps).build(nb.id)
    assert enc.calls == 2
    # 2本目のソースを追加して再実行 → 差分の2ページ分のみembedされる
    _add_pdf_source(conn, nb, sources_dir, sid_hint="h2")
    await VisualIndexBuilder(deps=deps).build(nb.id)
    assert enc.calls == 4


async def test_page_failure_skips_and_continues(tmp_path):
    conn, nb, ps, sources_dir, assets_dir = _setup(tmp_path)
    _add_pdf_source(conn, nb, sources_dir)
    builder = VisualIndexBuilder(deps=BuilderDeps(
        conn=conn, visual_store=ps, encoder=FakeEncoder(fail_on_call=1),
        sources_dir=sources_dir, assets_dir=assets_dir,
        embedding_model_name="test-model",
    ))
    result = await builder.build(nb.id)
    assert result.indexed_pages == 1 and result.skipped_pages == 1  # 部分成功で継続


async def test_non_pdf_and_non_ready_sources_ignored(tmp_path):
    conn, nb, ps, sources_dir, assets_dir = _setup(tmp_path)
    create_source(conn, notebook_id=nb.id, kind="md", origin="a.md", content_hash="hm")
    pending = create_source(conn, notebook_id=nb.id, kind="pdf", origin="p.pdf", content_hash="hp")
    (sources_dir / f"{pending.id}.pdf").write_bytes(_two_page_pdf())  # READY にしない
    builder = VisualIndexBuilder(deps=BuilderDeps(
        conn=conn, visual_store=ps, encoder=FakeEncoder(),
        sources_dir=sources_dir, assets_dir=assets_dir,
        embedding_model_name="test-model",
    ))
    result = await builder.build(nb.id)
    assert result.indexed_pages == 0 and result.indexed_sources == 0


async def test_page_cooldown_sleeps_between_pages(tmp_path, monkeypatch):
    """回帰テスト: CPU全開バーストの連続実行がマシンの電源/熱マージンを削り
    BSODを誘発した(実機観測)。ページ間クールダウンで負荷デューティ比を下げる。"""
    import core.visual.index_builder as builder_mod

    sleeps: list[float] = []
    real_sleep = builder_mod.asyncio.sleep

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(builder_mod.asyncio, "sleep", fake_sleep)
    conn, nb, ps, sources_dir, assets_dir = _setup(tmp_path)
    _add_pdf_source(conn, nb, sources_dir)  # 2ページ
    builder = VisualIndexBuilder(deps=BuilderDeps(
        conn=conn, visual_store=ps, encoder=FakeEncoder(),
        sources_dir=sources_dir, assets_dir=assets_dir,
        embedding_model_name="test-model", page_cooldown_seconds=1.5,
    ))
    result = await builder.build(nb.id)
    assert result.indexed_pages == 2
    # 2ページ→最終ページの後は休まない=1回だけ
    assert sleeps == [1.5]


def _setup_unit(tmp_path, unit):
    """既存 _setup の unit 版。VisualUnitStore を返す。"""
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    vs = VectorStore(path=tmp_path / "q", dim=4)
    vs.ensure_collection()
    ps = VisualUnitStore(client=vs.client, unit=unit)
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    assets_dir = tmp_path / "assets"
    return conn, nb, ps, sources_dir, assets_dir


async def test_tile_build_saves_tile_pngs_and_vectors(tmp_path):
    conn, nb, ps, sources_dir, assets_dir = _setup_unit(tmp_path, "tile")
    sid = _add_pdf_source(conn, nb, sources_dir)
    enc = FakeEncoder()
    builder = VisualIndexBuilder(deps=BuilderDeps(
        conn=conn, visual_store=ps, encoder=enc,
        sources_dir=sources_dir, assets_dir=assets_dir,
        embedding_model_name="test-model",
        unit="tile", tile_rows=3, tile_cols=1, tile_overlap=0.1,
    ))
    result = await builder.build(nb.id)

    # 2ページ x 3タイル = 6 埋め込み
    assert enc.calls == 6
    assert result.indexed_tiles == 6
    assert result.indexed_pages == 2       # 分母はページのまま
    assert result.indexed_sources == 1
    for page in (1, 2):
        for tile in (0, 1, 2):
            assert (assets_dir / sid / "tiles" / f"{page}-{tile}.png").exists()
    # ページPNGは tile 構築では作られない(page 索引の領分)
    assert not (assets_dir / sid / "pages").exists()
    assert len(ps.search(query=[1.0, 1.0, 0.0, 0.0], notebook_id=nb.id, limit=20)) == 6


async def test_tile_progress_counts_pages_not_tiles(tmp_path):
    conn, nb, ps, sources_dir, assets_dir = _setup_unit(tmp_path, "tile")
    _add_pdf_source(conn, nb, sources_dir)
    log = []

    async def progress(done, total):
        log.append((done, total))

    builder = VisualIndexBuilder(deps=BuilderDeps(
        conn=conn, visual_store=ps, encoder=FakeEncoder(),
        sources_dir=sources_dir, assets_dir=assets_dir,
        embedding_model_name="test-model", progress=progress,
        unit="tile", tile_rows=3, tile_cols=1, tile_overlap=0.1,
    ))
    await builder.build(nb.id)
    assert log == [(1, 2), (2, 2)]   # ページ単位。done > total にならない


async def test_tile_and_page_indexes_are_tracked_independently(tmp_path):
    conn, nb, ps_tile, sources_dir, assets_dir = _setup_unit(tmp_path, "tile")
    from core.storage.visual_index_repo import list_indexed_source_ids

    sid = _add_pdf_source(conn, nb, sources_dir)
    await VisualIndexBuilder(deps=BuilderDeps(
        conn=conn, visual_store=ps_tile, encoder=FakeEncoder(),
        sources_dir=sources_dir, assets_dir=assets_dir,
        embedding_model_name="test-model", unit="tile",
    )).build(nb.id)

    assert list_indexed_source_ids(conn, nb.id, "tile") == {sid}
    # page 側は未構築のまま = tile を作っても page の差分構築はスキップされない
    assert list_indexed_source_ids(conn, nb.id, "page") == set()


async def test_tile_embed_failure_skips_page_and_continues(tmp_path):
    conn, nb, ps, sources_dir, assets_dir = _setup_unit(tmp_path, "tile")
    _add_pdf_source(conn, nb, sources_dir)
    builder = VisualIndexBuilder(deps=BuilderDeps(
        conn=conn, visual_store=ps, encoder=FakeEncoder(fail_on_call=1),
        sources_dir=sources_dir, assets_dir=assets_dir,
        embedding_model_name="test-model", unit="tile",
        tile_rows=3, tile_cols=1, tile_overlap=0.1,
    ))
    result = await builder.build(nb.id)
    # 1タイル目が落ちてもそのページの残タイル・次ページは続行する
    assert result.skipped_pages == 0        # ページ単位では成功扱い(部分成功)
    assert result.indexed_tiles == 5
    assert result.indexed_pages == 2


async def test_tile_cooldown_still_fires_per_page(tmp_path, monkeypatch):
    """クールダウンはページ境界のまま。タイル数だけ待たされないこと。"""
    import core.visual.index_builder as builder_mod

    conn, nb, ps, sources_dir, assets_dir = _setup_unit(tmp_path, "tile")
    _add_pdf_source(conn, nb, sources_dir)
    sleeps: list[float] = []
    real_sleep = builder_mod.asyncio.sleep

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(builder_mod.asyncio, "sleep", fake_sleep)
    await VisualIndexBuilder(deps=BuilderDeps(
        conn=conn, visual_store=ps, encoder=FakeEncoder(),
        sources_dir=sources_dir, assets_dir=assets_dir,
        embedding_model_name="test-model", unit="tile",
        tile_rows=3, tile_cols=1, tile_overlap=0.1,
        page_cooldown_seconds=1.5,
    )).build(nb.id)
    # 2ページ = 1回だけ(タイル6枚でも6回にならない)
    assert sleeps == [1.5]


def test_building_registry_is_keyed_by_unit():
    from core.visual.index_builder import is_building, mark_building, unmark_building

    assert is_building("nb1", "page") is False
    mark_building("nb1", "tile")
    assert is_building("nb1", "tile") is True
    assert is_building("nb1", "page") is False   # 単位ごとに独立
    unmark_building("nb1", "tile")
    assert is_building("nb1", "tile") is False

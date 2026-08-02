import pytest

from core.storage.vector_store import VectorStore
from core.storage.visual_store import (
    PAGE_COLLECTION,
    TILE_COLLECTION,
    UnitVector,
    VisualUnitStore,
)

pytestmark = pytest.mark.qdrant

UNITS = ["page", "tile"]


def _store(tmp_path, unit="page"):
    vs = VectorStore(path=tmp_path / "q", dim=4)
    vs.ensure_collection()
    # Qdrant ローカルモードは1パス1クライアント制約があるため client を共有する
    return vs, VisualUnitStore(client=vs.client, unit=unit)


def _uv(unit, *, source_id="s1", page=1, tile=0, vec=None, nb="nb1"):
    return UnitVector(
        source_id=source_id,
        page=page,
        vector=vec or [1.0, 0.0, 0.0, 0.0],
        notebook_id=nb,
        embedding_model="test-model",
        built_at="t1",
        tile_index=(tile if unit == "tile" else None),
    )


@pytest.mark.parametrize("unit", UNITS)
def test_upsert_and_search_roundtrip(tmp_path, unit):
    _, ps = _store(tmp_path, unit)
    ps.ensure_collection(dim=4)
    assert ps.collection_dim() == 4
    ps.upsert_units([
        _uv(unit, page=1),
        _uv(unit, page=2, vec=[0.0, 1.0, 0.0, 0.0]),
    ])
    hits = ps.search(query=[1.0, 0.0, 0.0, 0.0], notebook_id="nb1", limit=5)
    assert hits[0].source_id == "s1" and hits[0].page == 1
    assert hits[0].score >= hits[-1].score


@pytest.mark.parametrize("unit", UNITS)
def test_search_scoped_to_notebook(tmp_path, unit):
    _, ps = _store(tmp_path, unit)
    ps.ensure_collection(dim=4)
    ps.upsert_units([_uv(unit, nb="nb1"), _uv(unit, source_id="s2", nb="nb2")])
    hits = ps.search(query=[1.0, 0.0, 0.0, 0.0], notebook_id="nb2", limit=5)
    assert {h.source_id for h in hits} == {"s2"}


@pytest.mark.parametrize("unit", UNITS)
def test_upsert_same_key_overwrites(tmp_path, unit):
    """決定的IDの契約テスト。再構築で重複点にならない。"""
    _, ps = _store(tmp_path, unit)
    ps.ensure_collection(dim=4)
    ps.upsert_units([_uv(unit, page=1)])
    ps.upsert_units([_uv(unit, page=1, vec=[0.0, 0.0, 1.0, 0.0])])
    hits = ps.search(query=[0.0, 0.0, 1.0, 0.0], notebook_id="nb1", limit=5)
    assert len(hits) == 1


@pytest.mark.parametrize("unit", UNITS)
def test_delete_by_source_and_notebook(tmp_path, unit):
    _, ps = _store(tmp_path, unit)
    ps.ensure_collection(dim=4)
    ps.upsert_units([_uv(unit, source_id="s1"), _uv(unit, source_id="s2", page=1)])
    ps.delete_by_source("s1")
    hits = ps.search(query=[1.0, 0.0, 0.0, 0.0], notebook_id="nb1", limit=5)
    assert {h.source_id for h in hits} == {"s2"}
    ps.delete_by_notebook("nb1")
    assert ps.search(query=[1.0, 0.0, 0.0, 0.0], notebook_id="nb1", limit=5) == []


@pytest.mark.parametrize("unit", UNITS)
def test_collection_absent_returns_none_dim(tmp_path, unit):
    _, ps = _store(tmp_path, unit)
    assert ps.collection_dim() is None
    assert ps.search(query=[1.0, 0.0, 0.0, 0.0], notebook_id="nb1", limit=5) == []


@pytest.mark.parametrize("unit", UNITS)
def test_search_scoped_to_source_ids(tmp_path, unit):
    """最終レビュー I5: source_ids を指定すると、そのソースのヒットだけが返る。"""
    _, ps = _store(tmp_path, unit)
    ps.ensure_collection(dim=4)
    ps.upsert_units([
        _uv(unit, source_id="s1", page=1, vec=[1.0, 0.0, 0.0, 0.0]),
        _uv(unit, source_id="s2", page=1, vec=[1.0, 0.0, 0.0, 0.0]),
        _uv(unit, source_id="s3", page=1, vec=[1.0, 0.0, 0.0, 0.0]),
    ])
    hits = ps.search(
        query=[1.0, 0.0, 0.0, 0.0], notebook_id="nb1", limit=10, source_ids=["s1", "s2"]
    )
    assert {h.source_id for h in hits} == {"s1", "s2"}


@pytest.mark.parametrize("unit", UNITS)
def test_search_without_source_ids_returns_all(tmp_path, unit):
    """source_ids=None(既定)のときは従来どおり全件返る。"""
    _, ps = _store(tmp_path, unit)
    ps.ensure_collection(dim=4)
    ps.upsert_units([
        _uv(unit, source_id="s1", page=1, vec=[1.0, 0.0, 0.0, 0.0]),
        _uv(unit, source_id="s2", page=1, vec=[1.0, 0.0, 0.0, 0.0]),
    ])
    hits = ps.search(query=[1.0, 0.0, 0.0, 0.0], notebook_id="nb1", limit=10)
    assert {h.source_id for h in hits} == {"s1", "s2"}


# --- タイル固有 --------------------------------------------------------------


def test_tiles_of_same_page_are_distinct_points(tmp_path):
    """同一ページの複数タイルが互いを上書きしないこと(点IDに tile_index が入る)。"""
    _, ps = _store(tmp_path, "tile")
    ps.ensure_collection(dim=4)
    ps.upsert_units([
        _uv("tile", page=1, tile=0, vec=[1.0, 0.0, 0.0, 0.0]),
        _uv("tile", page=1, tile=1, vec=[0.0, 1.0, 0.0, 0.0]),
        _uv("tile", page=1, tile=2, vec=[0.0, 0.0, 1.0, 0.0]),
    ])
    hits = ps.search(query=[1.0, 1.0, 1.0, 0.0], notebook_id="nb1", limit=10)
    assert len(hits) == 3
    assert sorted(h.tile_index for h in hits) == [0, 1, 2]
    assert {h.page for h in hits} == {1}


def test_page_and_tile_use_separate_collections(tmp_path):
    vs = VectorStore(path=tmp_path / "q", dim=4)
    vs.ensure_collection()
    page_store = VisualUnitStore(client=vs.client, unit="page")
    tile_store = VisualUnitStore(client=vs.client, unit="tile")
    page_store.ensure_collection(dim=4)
    tile_store.ensure_collection(dim=4)
    page_store.upsert_units([_uv("page", page=1)])
    tile_store.upsert_units([_uv("tile", page=1, tile=0)])

    names = {c.name for c in vs.client.get_collections().collections}
    assert PAGE_COLLECTION in names and TILE_COLLECTION in names
    # 片方を消してももう片方は残る
    page_store.delete_by_notebook("nb1")
    assert page_store.search(query=[1.0, 0.0, 0.0, 0.0], notebook_id="nb1", limit=5) == []
    assert len(tile_store.search(query=[1.0, 0.0, 0.0, 0.0], notebook_id="nb1", limit=5)) == 1


def test_page_point_id_is_unchanged_from_stage3(tmp_path):
    """Stage 3 で構築済みの pages_visual を再構築不要にするための契約テスト。"""
    import uuid

    from core.storage.visual_store import _NS, _unit_point_id

    assert _unit_point_id("page", "src1", 3, None) == str(
        uuid.uuid5(_NS, "visualpage:src1:3")
    )
    assert _unit_point_id("tile", "src1", 3, 2) == str(
        uuid.uuid5(_NS, "visualtile:src1:3:2")
    )

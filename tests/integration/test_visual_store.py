import pytest

from core.storage.vector_store import VectorStore
from core.storage.visual_store import PageVector, VisualPageStore

pytestmark = pytest.mark.qdrant


def _store(tmp_path):
    vs = VectorStore(path=tmp_path / "q", dim=4)
    vs.ensure_collection()
    return vs, VisualPageStore(client=vs.client)


def _pv(source_id="s1", page=1, vec=None, nb="nb1"):
    return PageVector(
        source_id=source_id, page=page, vector=vec or [1.0, 0.0, 0.0, 0.0],
        notebook_id=nb, embedding_model="test-model", built_at="t1",
    )


def test_upsert_and_search_roundtrip(tmp_path):
    _, ps = _store(tmp_path)
    ps.ensure_collection(dim=4)
    assert ps.collection_dim() == 4
    ps.upsert_pages([_pv(page=1), _pv(page=2, vec=[0.0, 1.0, 0.0, 0.0])])
    hits = ps.search(query=[1.0, 0.0, 0.0, 0.0], notebook_id="nb1", limit=5)
    assert hits[0].source_id == "s1" and hits[0].page == 1
    assert hits[0].score >= hits[-1].score


def test_search_scoped_to_notebook(tmp_path):
    _, ps = _store(tmp_path)
    ps.ensure_collection(dim=4)
    ps.upsert_pages([_pv(nb="nb1"), _pv(source_id="s2", nb="nb2")])
    hits = ps.search(query=[1.0, 0.0, 0.0, 0.0], notebook_id="nb2", limit=5)
    assert {h.source_id for h in hits} == {"s2"}


def test_upsert_same_page_overwrites(tmp_path):
    _, ps = _store(tmp_path)
    ps.ensure_collection(dim=4)
    ps.upsert_pages([_pv(page=1)])
    ps.upsert_pages([_pv(page=1, vec=[0.0, 0.0, 1.0, 0.0])])  # 再構築
    hits = ps.search(query=[0.0, 0.0, 1.0, 0.0], notebook_id="nb1", limit=5)
    assert len(hits) == 1  # 重複点にならない(決定的ID)


def test_delete_by_source_and_notebook(tmp_path):
    _, ps = _store(tmp_path)
    ps.ensure_collection(dim=4)
    ps.upsert_pages([_pv(source_id="s1"), _pv(source_id="s2", page=1)])
    ps.delete_by_source("s1")
    hits = ps.search(query=[1.0, 0.0, 0.0, 0.0], notebook_id="nb1", limit=5)
    assert {h.source_id for h in hits} == {"s2"}
    ps.delete_by_notebook("nb1")
    assert ps.search(query=[1.0, 0.0, 0.0, 0.0], notebook_id="nb1", limit=5) == []


def test_collection_absent_returns_none_dim(tmp_path):
    _, ps = _store(tmp_path)
    assert ps.collection_dim() is None
    assert ps.search(query=[1.0, 0.0, 0.0, 0.0], notebook_id="nb1", limit=5) == []

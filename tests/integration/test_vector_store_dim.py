import pytest

from core.storage.vector_store import ChunkVector, VectorStore


@pytest.mark.qdrant
def test_collection_dim_none_before_ensure(tmp_path):
    vs = VectorStore(path=tmp_path / "qdrant", dim=4)
    # collection 未作成 -> None
    assert vs.collection_dim() is None


@pytest.mark.qdrant
def test_collection_dim_reports_size(tmp_path):
    vs = VectorStore(path=tmp_path / "qdrant", dim=4)
    vs.ensure_collection()
    assert vs.collection_dim() == 4


@pytest.mark.qdrant
def test_recreate_collection_changes_dim_and_drops_points(tmp_path):
    vs = VectorStore(path=tmp_path / "qdrant", dim=4)
    vs.ensure_collection()
    vs.upsert(
        [
            ChunkVector(
                id="a" * 26,
                vector=[1, 0, 0, 0],
                notebook_id="NB",
                source_id="S",
                source_kind="md",
                page=None,
                heading_path=None,
                ord=0,
            )
        ]
    )
    assert vs.collection_dim() == 4
    # 再作成で新しい dim、既存ポイントは消える
    vs.recreate_collection(8)
    assert vs.collection_dim() == 8
    hits = vs.search(query=[0.0] * 8, notebook_id="NB", limit=10)
    assert hits == []
    # 新 dim で upsert/search が成立する
    vs.upsert(
        [
            ChunkVector(
                id="b" * 26,
                vector=[1, 0, 0, 0, 0, 0, 0, 0],
                notebook_id="NB",
                source_id="S2",
                source_kind="md",
                page=None,
                heading_path=None,
                ord=0,
            )
        ]
    )
    hits2 = vs.search(query=[1, 0, 0, 0, 0, 0, 0, 0], notebook_id="NB", limit=10)
    assert [h.id for h in hits2] == ["b" * 26]

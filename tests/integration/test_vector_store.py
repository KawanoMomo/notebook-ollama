import pytest
from core.storage.vector_store import VectorStore, ChunkVector

@pytest.mark.qdrant
def test_upsert_and_search(tmp_path):
    vs = VectorStore(path=tmp_path / "qdrant", dim=4)
    vs.ensure_collection()
    vectors = [
        ChunkVector(
            id="01HF" + str(i).rjust(22, "0"),
            vector=[1.0, 0.0, 0.0, float(i)],
            notebook_id="nb1",
            source_id=f"src{i}",
            source_kind="md",
            page=i + 1,
            heading_path="h",
            ord=i,
        )
        for i in range(3)
    ]
    vs.upsert(vectors)
    hits = vs.search(query=[1.0, 0.0, 0.0, 0.0], notebook_id="nb1", limit=2)
    assert len(hits) == 2
    assert all(h.notebook_id == "nb1" for h in hits)

@pytest.mark.qdrant
def test_search_filters_by_notebook(tmp_path):
    vs = VectorStore(path=tmp_path / "qdrant", dim=4)
    vs.ensure_collection()
    vs.upsert([
        ChunkVector(id="a"*26, vector=[1, 0, 0, 0], notebook_id="A",
                    source_id="s1", source_kind="md", page=None, heading_path=None, ord=0),
        ChunkVector(id="b"*26, vector=[1, 0, 0, 0], notebook_id="B",
                    source_id="s2", source_kind="md", page=None, heading_path=None, ord=0),
    ])
    hits = vs.search(query=[1, 0, 0, 0], notebook_id="A", limit=10)
    assert [h.id for h in hits] == ["a"*26]

@pytest.mark.qdrant
def test_delete_by_source(tmp_path):
    vs = VectorStore(path=tmp_path / "qdrant", dim=4)
    vs.ensure_collection()
    vs.upsert([
        ChunkVector(id="x"*26, vector=[1, 0, 0, 0], notebook_id="A",
                    source_id="DEL", source_kind="md", page=None, heading_path=None, ord=0),
    ])
    vs.delete_by_source("DEL")
    hits = vs.search(query=[1, 0, 0, 0], notebook_id="A", limit=10)
    assert hits == []

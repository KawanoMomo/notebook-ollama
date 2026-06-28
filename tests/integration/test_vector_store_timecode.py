import pytest
from core.storage.vector_store import VectorStore, ChunkVector


@pytest.mark.qdrant
def test_search_returns_timecode_and_channel(tmp_path):
    vs = VectorStore(path=tmp_path / "qdrant", dim=3)
    vs.ensure_collection()
    vs.upsert([ChunkVector(
        id="c1", vector=[0.1, 0.2, 0.3], notebook_id="nb", source_id="src",
        source_kind="recording", page=None, heading_path=None, ord=0,
        start_ms=12340, end_ms=12980, speaker="相手1", channel="system",
    )])
    hits = vs.search(query=[0.1, 0.2, 0.3], notebook_id="nb", limit=1)
    assert hits[0].start_ms == 12340
    assert hits[0].end_ms == 12980
    assert hits[0].speaker == "相手1"
    assert hits[0].channel == "system"


@pytest.mark.qdrant
def test_rename_speaker_updates_payload_within_source(tmp_path):
    vs = VectorStore(path=tmp_path / "qdrant", dim=3)
    vs.ensure_collection()
    vs.upsert([
        ChunkVector(
            id="c1", vector=[0.1, 0.2, 0.3], notebook_id="nb", source_id="src",
            source_kind="recording", page=None, heading_path=None, ord=0,
            speaker="相手1",
        ),
        ChunkVector(
            id="c2", vector=[0.4, 0.5, 0.6], notebook_id="nb", source_id="src",
            source_kind="recording", page=None, heading_path=None, ord=1,
            speaker="あなた",
        ),
        ChunkVector(
            id="c3", vector=[0.7, 0.8, 0.9], notebook_id="nb", source_id="other",
            source_kind="recording", page=None, heading_path=None, ord=0,
            speaker="相手1",
        ),
    ])

    vs.rename_speaker("src", "相手1", "田中さん")

    by_id = {h.id: h.speaker for h in vs.search(query=[0.1, 0.2, 0.3], notebook_id="nb", limit=10)}
    assert by_id["c1"] == "田中さん"  # renamed
    assert by_id["c2"] == "あなた"  # other speaker untouched
    assert by_id["c3"] == "相手1"  # other source untouched (within-source scope)

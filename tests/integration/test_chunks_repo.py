from core.storage.chunks_repo import (
    ChunkRecord,
    delete_chunks_for_source,
    get_chunks_by_ids,
    insert_chunks,
    rename_speaker_in_source,
)
from core.storage.database import connect, migrate
from core.storage.notebooks_repo import create_notebook
from core.storage.sources_repo import create_source


def _ctx(tmp_path):
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    src = create_source(conn, notebook_id=nb.id, kind="md", content_hash="h")
    return conn, nb, src


def _chunk(nb_id, src_id, ord_: int, text: str, speaker: str | None = None) -> ChunkRecord:
    return ChunkRecord(
        id="01HF" + str(ord_).rjust(22, "0"),
        source_id=src_id,
        notebook_id=nb_id,
        ord=ord_,
        page=ord_ + 1,
        heading_path="Ch1 > S1",
        text=text,
        token_count=len(text),
        speaker=speaker,
    )


def test_insert_and_fetch_chunks(tmp_path):
    conn, nb, src = _ctx(tmp_path)
    chunks = [_chunk(nb.id, src.id, i, f"chunk{i}") for i in range(3)]
    insert_chunks(conn, chunks)
    fetched = get_chunks_by_ids(conn, [c.id for c in chunks])
    assert {c.id for c in fetched} == {c.id for c in chunks}


def test_get_chunks_preserves_request_order(tmp_path):
    conn, nb, src = _ctx(tmp_path)
    chunks = [_chunk(nb.id, src.id, i, f"chunk{i}") for i in range(3)]
    insert_chunks(conn, chunks)
    ids = [chunks[2].id, chunks[0].id, chunks[1].id]
    fetched = get_chunks_by_ids(conn, ids)
    assert [c.id for c in fetched] == ids


def test_delete_chunks_for_source(tmp_path):
    conn, nb, src = _ctx(tmp_path)
    insert_chunks(conn, [_chunk(nb.id, src.id, 0, "x")])
    delete_chunks_for_source(conn, src.id)
    assert get_chunks_by_ids(conn, [_chunk(nb.id, src.id, 0, "x").id]) == []


def test_list_chunks_for_source_orders_by_ord_asc(tmp_path):
    from core.storage.chunks_repo import list_chunks_for_source

    conn, nb, src = _ctx(tmp_path)
    # insert out of ord order
    insert_chunks(conn, [_chunk(nb.id, src.id, 2, "third")])
    insert_chunks(conn, [_chunk(nb.id, src.id, 0, "first")])
    insert_chunks(conn, [_chunk(nb.id, src.id, 1, "second")])

    fetched = list_chunks_for_source(conn, src.id)
    assert [c.ord for c in fetched] == [0, 1, 2]
    assert [c.text for c in fetched] == ["first", "second", "third"]


def test_list_chunks_for_source_scopes_to_source(tmp_path):
    from core.storage.chunks_repo import list_chunks_for_source
    from core.storage.sources_repo import create_source

    conn, nb, src = _ctx(tmp_path)
    other = create_source(conn, notebook_id=nb.id, kind="md", content_hash="h2")
    # Use different ord values to avoid UNIQUE constraint collision on id
    insert_chunks(conn, [_chunk(nb.id, src.id, 10, "mine")])
    insert_chunks(conn, [_chunk(nb.id, other.id, 20, "theirs")])

    fetched = list_chunks_for_source(conn, src.id)
    assert [c.text for c in fetched] == ["mine"]


def test_rename_speaker_in_source_updates_matching_and_returns_count(tmp_path):
    conn, nb, src = _ctx(tmp_path)
    insert_chunks(conn, [_chunk(nb.id, src.id, 0, "a", speaker="相手1")])
    insert_chunks(conn, [_chunk(nb.id, src.id, 1, "b", speaker="相手1")])
    insert_chunks(conn, [_chunk(nb.id, src.id, 2, "c", speaker="あなた")])

    updated = rename_speaker_in_source(conn, src.id, "相手1", "田中さん")

    assert updated == 2
    rows = conn.execute(
        "SELECT speaker FROM chunks WHERE source_id = ? ORDER BY ord", (src.id,)
    ).fetchall()
    assert [r["speaker"] for r in rows] == ["田中さん", "田中さん", "あなた"]


def test_rename_speaker_in_source_scopes_to_source(tmp_path):
    from core.storage.sources_repo import create_source

    conn, nb, src = _ctx(tmp_path)
    other = create_source(conn, notebook_id=nb.id, kind="md", content_hash="h2")
    insert_chunks(conn, [_chunk(nb.id, src.id, 0, "mine", speaker="相手1")])
    insert_chunks(conn, [_chunk(nb.id, other.id, 1, "theirs", speaker="相手1")])

    updated = rename_speaker_in_source(conn, src.id, "相手1", "田中さん")

    assert updated == 1
    other_speaker = conn.execute(
        "SELECT speaker FROM chunks WHERE source_id = ?", (other.id,)
    ).fetchone()["speaker"]
    assert other_speaker == "相手1"


def test_rename_speaker_in_source_unknown_label_returns_zero(tmp_path):
    conn, nb, src = _ctx(tmp_path)
    insert_chunks(conn, [_chunk(nb.id, src.id, 0, "a", speaker="相手1")])
    updated = rename_speaker_in_source(conn, src.id, "存在しない", "田中さん")
    assert updated == 0

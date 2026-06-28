import sqlite3
from core.storage.database import migrate
from core.storage.chunks_repo import ChunkRecord, insert_chunks, get_chunks_by_ids


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    migrate(c)
    c.execute("INSERT INTO notebooks(id,name,created_at,updated_at) VALUES('nb','n','t','t')")
    c.execute(
        "INSERT INTO sources(id,notebook_id,kind,status,created_at,updated_at) "
        "VALUES('src','nb','recording','ready','t','t')"
    )
    return c


def test_insert_and_read_back_timecode():
    conn = _conn()
    rec = ChunkRecord(
        id="c1", source_id="src", notebook_id="nb", ord=0, page=None,
        heading_path=None, text="hello", token_count=1,
        start_ms=12340, end_ms=12980, speaker="相手1",
    )
    insert_chunks(conn, [rec])
    got = get_chunks_by_ids(conn, ["c1"])[0]
    assert got.start_ms == 12340
    assert got.end_ms == 12980
    assert got.speaker == "相手1"

import sqlite3

from core.storage.database import migrate
from core.storage.migrations import run_chunk_timecode_migration


def _cols(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_chunks_have_timecode_columns_after_migrate():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    migrate(conn)
    cols = _cols(conn, "chunks")
    assert {"start_ms", "end_ms", "speaker"} <= cols


def test_migration_is_idempotent():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    migrate(conn)
    run_chunk_timecode_migration(conn)  # second run must not raise
    cols = _cols(conn, "chunks")
    assert {"start_ms", "end_ms", "speaker"} <= cols

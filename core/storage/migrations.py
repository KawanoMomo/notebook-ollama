from __future__ import annotations

import sqlite3

_CHUNK_TIMECODE_COLUMNS = (
    ("start_ms", "INTEGER"),
    ("end_ms", "INTEGER"),
    ("speaker", "TEXT"),
)


def run_chunk_timecode_migration(conn: sqlite3.Connection) -> None:
    """Add start_ms/end_ms/speaker to chunks if missing. Idempotent."""
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(chunks)")}
    for name, sqltype in _CHUNK_TIMECODE_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE chunks ADD COLUMN {name} {sqltype}")

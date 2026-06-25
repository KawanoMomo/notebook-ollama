from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(db_path),
        isolation_level=None,
        check_same_thread=False,
        timeout=30,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(sql)
    from core.storage.migrations import (
        run_adr_migration,
        run_chunk_timecode_migration,
        run_summary_migration,
    )
    run_chunk_timecode_migration(conn)
    run_summary_migration(conn)
    run_adr_migration(conn)

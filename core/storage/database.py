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
        run_chunk_assets_migration,
        run_chunk_kind_migration,
        run_chunk_timecode_migration,
        run_desc_chunk_id_migration,
        run_message_truncated_migration,
        run_source_error_remediation_migration,
        run_summary_migration,
        run_visual_index_migration,
    )
    run_chunk_timecode_migration(conn)
    run_summary_migration(conn)
    run_adr_migration(conn)
    run_chunk_assets_migration(conn)
    run_message_truncated_migration(conn)
    run_chunk_kind_migration(conn)
    run_desc_chunk_id_migration(conn)
    run_visual_index_migration(conn)
    run_source_error_remediation_migration(conn)

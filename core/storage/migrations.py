from __future__ import annotations

import sqlite3

_CHUNK_TIMECODE_COLUMNS = (
    ("start_ms", "INTEGER"),
    ("end_ms", "INTEGER"),
    ("speaker", "TEXT"),
)

_SOURCE_SUMMARY_COLUMNS = (
    ("summary", "TEXT"),
    ("summary_status", "TEXT"),
)

_SOURCE_ADR_COLUMNS = (
    ("adr_draft", "TEXT"),
    ("adr_status", "TEXT"),
    ("adr_template", "TEXT"),
    ("adr_confidence", "TEXT"),
    ("adr_generated_at", "TEXT"),
)

_MESSAGE_TRUNCATED_COLUMNS = (
    ("truncated", "INTEGER NOT NULL DEFAULT 0"),
)


def run_chunk_timecode_migration(conn: sqlite3.Connection) -> None:
    """Add start_ms/end_ms/speaker to chunks if missing. Idempotent."""
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(chunks)")}
    for name, sqltype in _CHUNK_TIMECODE_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE chunks ADD COLUMN {name} {sqltype}")


def run_summary_migration(conn: sqlite3.Connection) -> None:
    """Add summary/summary_status to sources if missing. Idempotent."""
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(sources)")}
    for name, sqltype in _SOURCE_SUMMARY_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE sources ADD COLUMN {name} {sqltype}")


def run_adr_migration(conn: sqlite3.Connection) -> None:
    """Add adr_draft/adr_status/adr_template/adr_confidence/adr_generated_at to
    sources if missing. Idempotent. ALTER TABLE は SQLite では暗黙トランザクション
    なので autocommit (`isolation_level=None`) でも順次 ADD で OK。"""
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(sources)")}
    for name, sqltype in _SOURCE_ADR_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE sources ADD COLUMN {name} {sqltype}")


def run_message_truncated_migration(conn: sqlite3.Connection) -> None:
    """Add truncated to messages if missing. Idempotent."""
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(messages)")}
    for name, sqltype in _MESSAGE_TRUNCATED_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {name} {sqltype}")

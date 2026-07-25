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


def run_chunk_assets_migration(conn: sqlite3.Connection) -> None:
    """chunk_assets テーブルを作成。Idempotent。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chunk_assets (
          id          TEXT PRIMARY KEY,
          source_id   TEXT NOT NULL,
          chunk_id    TEXT,
          kind        TEXT NOT NULL,            -- 'table' | 'figure'
          page        INTEGER,
          bbox_json   TEXT,
          html        TEXT,
          md_snippet  TEXT,
          image_path  TEXT,
          created_at  TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunk_assets_source ON chunk_assets(source_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunk_assets_chunk ON chunk_assets(chunk_id)"
    )


def run_message_truncated_migration(conn: sqlite3.Connection) -> None:
    """Add truncated to messages if missing. Idempotent."""
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(messages)")}
    for name, sqltype in _MESSAGE_TRUNCATED_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {name} {sqltype}")


_CHUNK_KIND_COLUMNS = (("kind", "TEXT NOT NULL DEFAULT 'text'"),)


def run_chunk_kind_migration(conn: sqlite3.Connection) -> None:
    """Add chunks.kind to mark chunk type (text/figure_desc). Idempotent."""
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(chunks)")}
    for name, sqltype in _CHUNK_KIND_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE chunks ADD COLUMN {name} {sqltype}")


_DESC_CHUNK_ID_COLUMNS = (("desc_chunk_id", "TEXT"),)


def run_desc_chunk_id_migration(conn: sqlite3.Connection) -> None:
    """Add chunk_assets.desc_chunk_id to link to description chunk. Idempotent."""
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(chunk_assets)")}
    for name, sqltype in _DESC_CHUNK_ID_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE chunk_assets ADD COLUMN {name} {sqltype}")


def run_visual_index_migration(conn: sqlite3.Connection) -> None:
    """Add visual_index_meta / visual_index_sources (Stage 3). Idempotent."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS visual_index_meta (
          notebook_id TEXT PRIMARY KEY,
          embedding_model TEXT NOT NULL,
          built_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS visual_index_sources (
          source_id TEXT PRIMARY KEY,
          notebook_id TEXT NOT NULL,
          page_count INTEGER NOT NULL,
          built_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_visual_index_sources_nb "
        "ON visual_index_sources(notebook_id)"
    )

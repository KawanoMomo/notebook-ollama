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

# AppError.remediation(対処法)の保存先。これが無いと、パーサ等が用意している
# 対処文が update_source_status の時点で捨てられ、UI には英語混じりの message
# だけが出る(実機FB 2026-07-26: 画像PDFの取り込み失敗で対処が分からなかった)。
_SOURCE_ERROR_REMEDIATION_COLUMNS = (
    ("error_remediation", "TEXT"),
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


def run_source_error_remediation_migration(conn: sqlite3.Connection) -> None:
    """Add error_remediation to sources if missing. Idempotent."""
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(sources)")}
    for name, sqltype in _SOURCE_ERROR_REMEDIATION_COLUMNS:
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
    # NOTE: このインデックスは run_visual_index_unit_migration が
    # (notebook_id, unit) で張り直す(同名なので CREATE INDEX IF NOT EXISTS は
    # 以後スキップされる)。新規DBでも最終的な定義は複合列になる。
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_visual_index_sources_nb "
        "ON visual_index_sources(notebook_id)"
    )


# --- Stage 4: visual_index を unit('page' | 'tile') 単位で管理する -----------
#
# ページ索引とタイル索引(PixelRAG式)を同一ノートブックで独立に構築するため、
# PK を (notebook_id, unit) / (source_id, unit) に複合化する。SQLite には PK を
# 変更する ALTER TABLE が無いので、公式手順(https://sqlite.org/lang_altertable.html
# の "Making Other Kinds Of Table Schema Changes")どおりテーブルを作り直す。
# このリポジトリ初のテーブル再作成マイグレーション。

_VISUAL_INDEX_META_NEW_DDL = """
CREATE TABLE visual_index_meta_new (
  notebook_id     TEXT NOT NULL,
  unit            TEXT NOT NULL DEFAULT 'page',  -- 'page' | 'tile'
  embedding_model TEXT NOT NULL,
  built_at        TEXT NOT NULL,
  PRIMARY KEY (notebook_id, unit)
)
"""

_VISUAL_INDEX_SOURCES_NEW_DDL = """
CREATE TABLE visual_index_sources_new (
  source_id   TEXT NOT NULL,
  unit        TEXT NOT NULL DEFAULT 'page',      -- 'page' | 'tile'
  notebook_id TEXT NOT NULL,
  page_count  INTEGER NOT NULL,
  built_at    TEXT NOT NULL,
  PRIMARY KEY (source_id, unit)
)
"""


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r["name"] == column for r in conn.execute(f"PRAGMA table_info({table})"))


def _ensure_visual_index_indexes(conn: sqlite3.Connection) -> None:
    # 複合PK (source_id, unit) は notebook_id 検索を助けないので明示的に張る。
    # DROP TABLE で旧インデックスも消えるため、作り直しは必須。
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_visual_index_sources_nb "
        "ON visual_index_sources(notebook_id, unit)"
    )


def run_visual_index_unit_migration(conn: sqlite3.Connection) -> None:
    """visual_index_meta / visual_index_sources を unit 対応の複合PKに移行する。

    - visual_index_meta:    PRIMARY KEY(notebook_id)  -> PRIMARY KEY(notebook_id, unit)
    - visual_index_sources: PRIMARY KEY(source_id)    -> PRIMARY KEY(source_id, unit)
    - 既存行はすべて unit='page' として移行する

    Idempotent。unit 列が既にあれば何もしない(インデックスの補完のみ)。
    run_visual_index_migration より後に呼ぶこと(テーブルが無ければ no-op)。

    トランザクション: 呼び出し側の connect() は isolation_level=None(autocommit)
    なので、既存マイグレーションと同様 commit は呼ばない。ただしテーブル再作成は
    複数文にまたがり、途中で落ちるとテーブルが消えた状態で残るため、この関数
    だけは明示 BEGIN/COMMIT で原子性を確保する(呼び出し側が既にトランザクション
    中なら、その外側のトランザクションに委ねる)。

    PRAGMA foreign_keys: visual_index_* は FK を持たず、他テーブルからも参照
    されていない(schema.sql / migrations.py 全文で確認済み)。したがって
    再作成時に foreign_keys を OFF にする必要は無い。
    """
    if not (
        _table_exists(conn, "visual_index_meta")
        and _table_exists(conn, "visual_index_sources")
    ):
        return

    meta_needs = not _has_column(conn, "visual_index_meta", "unit")
    sources_needs = not _has_column(conn, "visual_index_sources", "unit")
    if not meta_needs and not sources_needs:
        _ensure_visual_index_indexes(conn)
        return

    owns_tx = not conn.in_transaction
    if owns_tx:
        conn.execute("BEGIN IMMEDIATE")
    try:
        if meta_needs:
            conn.execute("DROP TABLE IF EXISTS visual_index_meta_new")
            conn.execute(_VISUAL_INDEX_META_NEW_DDL)
            conn.execute(
                "INSERT INTO visual_index_meta_new"
                "(notebook_id, unit, embedding_model, built_at) "
                "SELECT notebook_id, 'page', embedding_model, built_at "
                "FROM visual_index_meta"
            )
            conn.execute("DROP TABLE visual_index_meta")
            conn.execute("ALTER TABLE visual_index_meta_new RENAME TO visual_index_meta")

        if sources_needs:
            conn.execute("DROP TABLE IF EXISTS visual_index_sources_new")
            conn.execute(_VISUAL_INDEX_SOURCES_NEW_DDL)
            conn.execute(
                "INSERT INTO visual_index_sources_new"
                "(source_id, unit, notebook_id, page_count, built_at) "
                "SELECT source_id, 'page', notebook_id, page_count, built_at "
                "FROM visual_index_sources"
            )
            conn.execute("DROP TABLE visual_index_sources")
            conn.execute(
                "ALTER TABLE visual_index_sources_new RENAME TO visual_index_sources"
            )

        _ensure_visual_index_indexes(conn)
    except Exception:
        if owns_tx:
            conn.execute("ROLLBACK")
        raise
    if owns_tx:
        conn.execute("COMMIT")

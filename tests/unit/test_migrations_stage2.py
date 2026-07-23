import sqlite3

from core.storage.chunks_repo import ChunkRecord, insert_chunks, list_chunks_for_source
from core.storage.migrations import (
    run_desc_chunk_id_migration, run_chunk_kind_migration, run_chunk_assets_migration,
)
from core.storage.assets_repo import (
    AssetRecord, insert_assets, list_assets_for_source, set_desc_chunk_link,
)


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # chunks テーブルは schema.sql 由来。テスト用に最小構成を作る。
    conn.execute(
        """
        CREATE TABLE chunks (
          id TEXT PRIMARY KEY, source_id TEXT, notebook_id TEXT, ord INTEGER,
          page INTEGER, heading_path TEXT, text TEXT, token_count INTEGER,
          start_ms INTEGER, end_ms INTEGER, speaker TEXT
        )
        """
    )
    run_chunk_kind_migration(conn)
    run_chunk_assets_migration(conn)
    run_desc_chunk_id_migration(conn)
    return conn


def test_chunk_kind_defaults_to_text_and_accepts_figure_desc():
    conn = _conn()
    rec = ChunkRecord(
        id="c1", source_id="s1", notebook_id="nb1", ord=0, page=1,
        heading_path=None, text="通常本文", token_count=3,
    )
    insert_chunks(conn, [rec])
    row = list_chunks_for_source(conn, "s1")[0]
    assert row.kind == "text"

    rec2 = ChunkRecord(
        id="c2", source_id="s1", notebook_id="nb1", ord=1, page=1,
        heading_path=None, text="図の説明文", token_count=4, kind="figure_desc",
    )
    insert_chunks(conn, [rec2])
    row2 = [r for r in list_chunks_for_source(conn, "s1") if r.id == "c2"][0]
    assert row2.kind == "figure_desc"


def test_migration_idempotent():
    conn = _conn()
    run_chunk_kind_migration(conn)
    run_desc_chunk_id_migration(conn)


def test_desc_chunk_id_link():
    conn = _conn()
    insert_assets(conn, [
        AssetRecord(
            id="a1", source_id="s1", chunk_id=None, kind="figure", page=1,
            bbox_json=None, html=None, md_snippet=None, image_path="s1/a1.png",
            created_at="t", desc_chunk_id=None,
        )
    ])
    set_desc_chunk_link(conn, "a1", "c2")
    row = list_assets_for_source(conn, "s1")[0]
    assert row.desc_chunk_id == "c2"

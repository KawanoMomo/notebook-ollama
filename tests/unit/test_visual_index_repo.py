import sqlite3

from core.storage.migrations import (
    run_visual_index_migration,
    run_visual_index_unit_migration,
)
from core.storage.visual_index_repo import (
    VisualIndexMeta,
    delete_indexed_source,
    delete_meta,
    get_meta,
    list_indexed_source_ids,
    mark_source_indexed,
    upsert_meta,
)


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_visual_index_migration(conn)
    run_visual_index_unit_migration(conn)
    return conn


def test_meta_roundtrip_and_overwrite():
    conn = _conn()
    assert get_meta(conn, "nb1") is None
    upsert_meta(conn, VisualIndexMeta(notebook_id="nb1", embedding_model="m1", built_at="t1"))
    got = get_meta(conn, "nb1")
    assert got is not None and got.embedding_model == "m1"
    # 再構築で上書き
    upsert_meta(conn, VisualIndexMeta(notebook_id="nb1", embedding_model="m2", built_at="t2"))
    got2 = get_meta(conn, "nb1")
    assert got2.embedding_model == "m2" and got2.built_at == "t2"


def test_indexed_sources_roundtrip():
    conn = _conn()
    mark_source_indexed(conn, notebook_id="nb1", source_id="s1", page_count=3, built_at="t1")
    mark_source_indexed(conn, notebook_id="nb1", source_id="s2", page_count=5, built_at="t1")
    assert list_indexed_source_ids(conn, "nb1") == {"s1", "s2"}
    # 再取込等での再索引は上書き(重複行にしない)
    mark_source_indexed(conn, notebook_id="nb1", source_id="s1", page_count=4, built_at="t2")
    assert list_indexed_source_ids(conn, "nb1") == {"s1", "s2"}
    delete_indexed_source(conn, "s1")
    assert list_indexed_source_ids(conn, "nb1") == {"s2"}


def test_delete_meta_removes_meta_and_source_rows():
    conn = _conn()
    upsert_meta(conn, VisualIndexMeta(notebook_id="nb1", embedding_model="m1", built_at="t1"))
    mark_source_indexed(conn, notebook_id="nb1", source_id="s1", page_count=3, built_at="t1")
    delete_meta(conn, "nb1")
    assert get_meta(conn, "nb1") is None
    assert list_indexed_source_ids(conn, "nb1") == set()


def test_migration_idempotent():
    conn = _conn()
    run_visual_index_migration(conn)  # 2回目でも例外なし


def test_page_and_tile_are_tracked_independently():
    conn = _conn()
    upsert_meta(conn, VisualIndexMeta(notebook_id="nb1", embedding_model="m", built_at="t1"))
    upsert_meta(
        conn,
        VisualIndexMeta(notebook_id="nb1", embedding_model="m", built_at="t2", unit="tile"),
    )
    assert get_meta(conn, "nb1").built_at == "t1"
    assert get_meta(conn, "nb1", "tile").built_at == "t2"

    mark_source_indexed(conn, notebook_id="nb1", source_id="s1", page_count=3, built_at="t1")
    mark_source_indexed(
        conn, notebook_id="nb1", source_id="s1", page_count=3, built_at="t2", unit="tile"
    )
    assert list_indexed_source_ids(conn, "nb1") == {"s1"}
    assert list_indexed_source_ids(conn, "nb1", "tile") == {"s1"}

    # 片方だけ消せる
    delete_meta(conn, "nb1", "tile")
    assert get_meta(conn, "nb1") is not None
    assert get_meta(conn, "nb1", "tile") is None
    assert list_indexed_source_ids(conn, "nb1") == {"s1"}
    assert list_indexed_source_ids(conn, "nb1", "tile") == set()


def test_delete_meta_without_unit_removes_all_units():
    conn = _conn()
    upsert_meta(conn, VisualIndexMeta(notebook_id="nb1", embedding_model="m", built_at="t1"))
    upsert_meta(
        conn,
        VisualIndexMeta(notebook_id="nb1", embedding_model="m", built_at="t2", unit="tile"),
    )
    delete_meta(conn, "nb1")
    assert get_meta(conn, "nb1") is None
    assert get_meta(conn, "nb1", "tile") is None


def test_delete_indexed_source_without_unit_removes_all_units():
    conn = _conn()
    mark_source_indexed(conn, notebook_id="nb1", source_id="s1", page_count=3, built_at="t1")
    mark_source_indexed(
        conn, notebook_id="nb1", source_id="s1", page_count=3, built_at="t1", unit="tile"
    )
    delete_indexed_source(conn, "s1")
    assert list_indexed_source_ids(conn, "nb1") == set()
    assert list_indexed_source_ids(conn, "nb1", "tile") == set()

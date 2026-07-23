import sqlite3

from core.storage.assets_repo import (
    AssetRecord,
    delete_assets_for_source,
    insert_assets,
    list_assets_for_chunk_ids,
    list_assets_for_source,
    set_chunk_link,
)
from core.storage.migrations import run_chunk_assets_migration


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_chunk_assets_migration(conn)
    return conn


def _asset(aid="a1", chunk_id=None, kind="table"):
    return AssetRecord(
        id=aid, source_id="s1", chunk_id=chunk_id, kind=kind, page=1,
        bbox_json="[0,0,100,50]", html="<table><tr><td>x</td></tr></table>",
        md_snippet="| x |", image_path=None, created_at="2026-07-20T00:00:00",
    )


def test_insert_and_list_roundtrip():
    conn = _conn()
    insert_assets(conn, [_asset()])
    rows = list_assets_for_source(conn, "s1")
    assert len(rows) == 1 and rows[0].kind == "table"


def test_chunk_link_and_lookup_by_chunk_ids():
    conn = _conn()
    insert_assets(conn, [_asset()])
    set_chunk_link(conn, "a1", "c9")
    by_chunk = list_assets_for_chunk_ids(conn, ["c9", "c-none"])
    assert [a.id for a in by_chunk["c9"]] == ["a1"]
    assert "c-none" not in by_chunk


def test_delete_for_source():
    conn = _conn()
    insert_assets(conn, [_asset(), _asset(aid="a2", kind="figure")])
    delete_assets_for_source(conn, "s1")
    assert list_assets_for_source(conn, "s1") == []


def test_migration_idempotent():
    conn = _conn()
    run_chunk_assets_migration(conn)  # 2回目でも例外なし

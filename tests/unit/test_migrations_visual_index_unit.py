# tests/unit/test_migrations_visual_index_unit.py
"""visual_index_* の unit 複合PK移行 (Stage 4)。

- 旧スキーマ (PK: notebook_id / source_id) から複合PKへ作り直す
- 既存行は unit='page' として保全される
- 何回流しても壊れない (冪等性)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.storage.migrations import (
    run_visual_index_migration,
    run_visual_index_unit_migration,
)

_LEGACY_DDL = """
CREATE TABLE visual_index_meta (
  notebook_id TEXT PRIMARY KEY,
  embedding_model TEXT NOT NULL,
  built_at TEXT NOT NULL
);
CREATE TABLE visual_index_sources (
  source_id TEXT PRIMARY KEY,
  notebook_id TEXT NOT NULL,
  page_count INTEGER NOT NULL,
  built_at TEXT NOT NULL
);
CREATE INDEX idx_visual_index_sources_nb ON visual_index_sources(notebook_id);
"""


def _pk_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """PRAGMA table_info の pk 列(1始まりの順序)から主キー構成列を復元する。"""
    rows = [r for r in conn.execute(f"PRAGMA table_info({table})") if r["pk"] > 0]
    return [r["name"] for r in sorted(rows, key=lambda r: r["pk"])]


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]


def _pk_index_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """PRAGMA index_list で origin='pk' の自動インデックスを探し、その構成列を返す。"""
    for idx in conn.execute(f"PRAGMA index_list({table})"):
        if idx["origin"] == "pk":
            info = list(conn.execute(f"PRAGMA index_info({idx['name']})"))
            return [r["name"] for r in sorted(info, key=lambda r: r["seqno"])]
    return []


def _index_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA index_list({table})")}


def _legacy_conn() -> sqlite3.Connection:
    # isolation_level=None は本番 database.connect() と同じ autocommit 設定。
    # 既定の isolation_level="" だと INSERT が暗黙トランザクションを開いてしまい、
    # マイグレーション側の BEGIN/COMMIT 経路を検証できなくなる。
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(_LEGACY_DDL)
    conn.execute(
        "INSERT INTO visual_index_meta(notebook_id, embedding_model, built_at) "
        "VALUES ('nb1', 'model-a', 't1'), ('nb2', 'model-b', 't2')"
    )
    conn.execute(
        "INSERT INTO visual_index_sources(source_id, notebook_id, page_count, built_at) "
        "VALUES ('s1', 'nb1', 3, 't1'), ('s2', 'nb1', 5, 't1'), ('s3', 'nb2', 7, 't2')"
    )
    return conn


def _migrated_conn() -> sqlite3.Connection:
    conn = _legacy_conn()
    run_visual_index_unit_migration(conn)
    return conn


# --- スキーマ ---------------------------------------------------------------


def test_meta_primary_key_becomes_notebook_id_and_unit():
    conn = _migrated_conn()
    assert _pk_columns(conn, "visual_index_meta") == ["notebook_id", "unit"]
    assert _pk_index_columns(conn, "visual_index_meta") == ["notebook_id", "unit"]


def test_sources_primary_key_becomes_source_id_and_unit():
    conn = _migrated_conn()
    assert _pk_columns(conn, "visual_index_sources") == ["source_id", "unit"]
    assert _pk_index_columns(conn, "visual_index_sources") == ["source_id", "unit"]


def test_existing_columns_are_kept():
    conn = _migrated_conn()
    assert set(_columns(conn, "visual_index_meta")) == {
        "notebook_id", "unit", "embedding_model", "built_at",
    }
    assert set(_columns(conn, "visual_index_sources")) == {
        "source_id", "unit", "notebook_id", "page_count", "built_at",
    }


def test_notebook_index_is_recreated_after_table_rebuild():
    conn = _migrated_conn()
    assert "idx_visual_index_sources_nb" in _index_names(conn, "visual_index_sources")


# --- データ保全 -------------------------------------------------------------


def test_existing_rows_are_migrated_as_unit_page():
    conn = _migrated_conn()
    meta = [
        tuple(r)
        for r in conn.execute(
            "SELECT notebook_id, unit, embedding_model, built_at "
            "FROM visual_index_meta ORDER BY notebook_id"
        )
    ]
    assert meta == [
        ("nb1", "page", "model-a", "t1"),
        ("nb2", "page", "model-b", "t2"),
    ]
    sources = [
        tuple(r)
        for r in conn.execute(
            "SELECT source_id, unit, notebook_id, page_count, built_at "
            "FROM visual_index_sources ORDER BY source_id"
        )
    ]
    assert sources == [
        ("s1", "page", "nb1", 3, "t1"),
        ("s2", "page", "nb1", 5, "t1"),
        ("s3", "page", "nb2", 7, "t2"),
    ]


def test_unit_defaults_to_page_when_omitted():
    """unit を書かない旧来の INSERT が残っていても 'page' 扱いになる。"""
    conn = _migrated_conn()
    conn.execute(
        "INSERT INTO visual_index_sources(source_id, notebook_id, page_count, built_at) "
        "VALUES ('s9', 'nb1', 1, 't9')"
    )
    row = conn.execute(
        "SELECT unit FROM visual_index_sources WHERE source_id = 's9'"
    ).fetchone()
    assert row["unit"] == "page"


# --- 複合PKの効き目 ---------------------------------------------------------


def test_page_and_tile_rows_coexist_for_same_id():
    conn = _migrated_conn()
    conn.execute(
        "INSERT INTO visual_index_meta(notebook_id, unit, embedding_model, built_at) "
        "VALUES ('nb1', 'tile', 'model-a', 't3')"
    )
    conn.execute(
        "INSERT INTO visual_index_sources"
        "(source_id, unit, notebook_id, page_count, built_at) "
        "VALUES ('s1', 'tile', 'nb1', 3, 't3')"
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM visual_index_meta WHERE notebook_id = 'nb1'"
    ).fetchone()[0] == 2
    assert conn.execute(
        "SELECT COUNT(*) FROM visual_index_sources WHERE source_id = 's1'"
    ).fetchone()[0] == 2


def test_duplicate_notebook_id_and_unit_is_rejected():
    conn = _migrated_conn()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO visual_index_meta(notebook_id, unit, embedding_model, built_at) "
            "VALUES ('nb1', 'page', 'x', 't')"
        )


def test_duplicate_source_id_and_unit_is_rejected():
    conn = _migrated_conn()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO visual_index_sources"
            "(source_id, unit, notebook_id, page_count, built_at) "
            "VALUES ('s1', 'page', 'nb1', 3, 't')"
        )


def test_on_conflict_on_composite_key_upserts():
    """repo 側 upsert が使う ON CONFLICT(notebook_id, unit) / (source_id, unit) が
    複合PKの unique index に解決されること。"""
    conn = _migrated_conn()
    conn.execute(
        "INSERT INTO visual_index_meta(notebook_id, unit, embedding_model, built_at) "
        "VALUES ('nb1', 'page', 'm2', 't9') ON CONFLICT(notebook_id, unit) DO UPDATE SET "
        "embedding_model=excluded.embedding_model, built_at=excluded.built_at"
    )
    row = conn.execute(
        "SELECT embedding_model, built_at FROM visual_index_meta "
        "WHERE notebook_id = 'nb1' AND unit = 'page'"
    ).fetchone()
    assert (row["embedding_model"], row["built_at"]) == ("m2", "t9")

    conn.execute(
        "INSERT INTO visual_index_sources"
        "(source_id, unit, notebook_id, page_count, built_at) "
        "VALUES ('s1', 'page', 'nb1', 42, 't9') ON CONFLICT(source_id, unit) DO UPDATE SET "
        "page_count=excluded.page_count, built_at=excluded.built_at"
    )
    row = conn.execute(
        "SELECT page_count FROM visual_index_sources "
        "WHERE source_id = 's1' AND unit = 'page'"
    ).fetchone()
    assert row["page_count"] == 42


# --- 冪等性 -----------------------------------------------------------------


def test_running_three_times_keeps_schema_and_data():
    conn = _legacy_conn()
    run_visual_index_unit_migration(conn)
    run_visual_index_unit_migration(conn)
    run_visual_index_unit_migration(conn)
    assert _pk_columns(conn, "visual_index_meta") == ["notebook_id", "unit"]
    assert _pk_columns(conn, "visual_index_sources") == ["source_id", "unit"]
    assert conn.execute("SELECT COUNT(*) FROM visual_index_meta").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM visual_index_sources").fetchone()[0] == 3
    assert "visual_index_meta_new" not in {
        r["name"] for r in conn.execute("SELECT name FROM sqlite_master")
    }


def test_second_run_does_not_reset_tile_rows():
    """移行済みDBに再実行しても tile 行が page に潰されたり消えたりしない。"""
    conn = _migrated_conn()
    conn.execute(
        "INSERT INTO visual_index_sources"
        "(source_id, unit, notebook_id, page_count, built_at) "
        "VALUES ('s1', 'tile', 'nb1', 3, 't3')"
    )
    run_visual_index_unit_migration(conn)
    units = [
        r["unit"]
        for r in conn.execute(
            "SELECT unit FROM visual_index_sources WHERE source_id = 's1' ORDER BY unit"
        )
    ]
    assert units == ["page", "tile"]


def test_failure_midway_rolls_back_and_retry_succeeds():
    """2テーブルの作り直しは 1 トランザクション。片方だけ移行された状態で残らない。

    失敗の注入: 作業用テーブル名と同名の VIEW を先に作っておくと
    DROP TABLE IF EXISTS では消えず CREATE TABLE が失敗する。
    """
    conn = _legacy_conn()
    conn.execute("CREATE VIEW visual_index_sources_new AS SELECT 1 AS x")
    with pytest.raises(sqlite3.OperationalError):
        run_visual_index_unit_migration(conn)
    assert not conn.in_transaction
    # meta 側の作り直しも巻き戻っている(中途半端な状態にならない)
    assert _pk_columns(conn, "visual_index_meta") == ["notebook_id"]
    assert conn.execute("SELECT COUNT(*) FROM visual_index_meta").fetchone()[0] == 2

    conn.execute("DROP VIEW visual_index_sources_new")
    run_visual_index_unit_migration(conn)
    assert _pk_columns(conn, "visual_index_meta") == ["notebook_id", "unit"]
    assert _pk_columns(conn, "visual_index_sources") == ["source_id", "unit"]
    assert conn.execute("SELECT COUNT(*) FROM visual_index_sources").fetchone()[0] == 3


def test_no_op_when_tables_are_absent():
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    run_visual_index_unit_migration(conn)  # 例外を出さない
    assert conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'visual_index%'"
    ).fetchone()[0] == 0


def test_runs_on_fresh_schema_from_run_visual_index_migration():
    """新規DB(run_visual_index_migration 直後)でも複合PKに揃う。"""
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    run_visual_index_migration(conn)
    run_visual_index_unit_migration(conn)
    assert _pk_columns(conn, "visual_index_meta") == ["notebook_id", "unit"]
    assert _pk_columns(conn, "visual_index_sources") == ["source_id", "unit"]
    # 2周目(次回起動時の migrate 相当)でも壊れない
    run_visual_index_migration(conn)
    run_visual_index_unit_migration(conn)
    assert _pk_columns(conn, "visual_index_sources") == ["source_id", "unit"]


def test_works_on_autocommit_connection_like_production(tmp_path: Path):
    """本番の connect() と同じ isolation_level=None / foreign_keys=ON で動く。"""
    db = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(str(db), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_LEGACY_DDL)
    conn.execute(
        "INSERT INTO visual_index_meta(notebook_id, embedding_model, built_at) "
        "VALUES ('nb1', 'm1', 't1')"
    )
    run_visual_index_unit_migration(conn)
    assert not conn.in_transaction  # COMMIT 済み(呼び出し側の commit 不要)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1  # 元に戻っている
    conn.close()

    # 別接続で読めること = 確実にコミットされている
    conn2 = sqlite3.connect(str(db), isolation_level=None)
    conn2.row_factory = sqlite3.Row
    assert _pk_columns(conn2, "visual_index_meta") == ["notebook_id", "unit"]
    row = conn2.execute("SELECT unit FROM visual_index_meta").fetchone()
    assert row["unit"] == "page"
    conn2.close()

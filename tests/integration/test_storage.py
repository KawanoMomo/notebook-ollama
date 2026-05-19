import sqlite3
from pathlib import Path
from core.storage.database import connect, migrate

def test_migrate_creates_all_tables(tmp_path: Path):
    db_path = tmp_path / "metadata.db"
    conn = connect(db_path)
    migrate(conn)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"notebooks", "sources", "chunks", "conversations", "messages"}.issubset(tables)

def test_migrate_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "metadata.db"
    conn = connect(db_path)
    migrate(conn)
    migrate(conn)  # should not raise

def test_connect_enables_foreign_keys(tmp_path: Path):
    conn = connect(tmp_path / "x.db")
    migrate(conn)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

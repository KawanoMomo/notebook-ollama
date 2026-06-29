from pathlib import Path

import pytest

from core.exceptions import AppError, ErrorCode
from core.storage.database import connect, migrate
from core.storage.notebooks_repo import (
    create_notebook,
    delete_notebook,
    get_notebook,
    list_notebooks,
    update_notebook,
)


def test_migrate_creates_all_tables(tmp_path: Path):
    db_path = tmp_path / "metadata.db"
    conn = connect(db_path)
    migrate(conn)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
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


def _migrated(tmp_path):
    conn = connect(tmp_path / "metadata.db")
    migrate(conn)
    return conn


def test_create_and_get_notebook(tmp_path):
    conn = _migrated(tmp_path)
    rec = create_notebook(conn, name="組み込み", description="firmware notes")
    assert rec.id and len(rec.id) == 26
    fetched = get_notebook(conn, rec.id)
    assert fetched.name == "組み込み"
    assert fetched.description == "firmware notes"
    assert fetched.default_model is None


def test_list_notebooks_ordered_by_updated_desc(tmp_path):
    import time

    conn = _migrated(tmp_path)
    a = create_notebook(conn, name="A")
    time.sleep(0.001)
    b = create_notebook(conn, name="B")
    time.sleep(0.001)
    update_notebook(conn, a.id, name="A2")
    items = list_notebooks(conn)
    assert [n.id for n in items] == [a.id, b.id]


def test_update_notebook_default_model(tmp_path):
    conn = _migrated(tmp_path)
    rec = create_notebook(conn, name="X")
    update_notebook(conn, rec.id, default_model="qwen2.5:14b")
    assert get_notebook(conn, rec.id).default_model == "qwen2.5:14b"


def test_get_missing_notebook_raises(tmp_path):
    conn = _migrated(tmp_path)
    with pytest.raises(AppError) as excinfo:
        get_notebook(conn, "missing-id")
    assert excinfo.value.code == ErrorCode.STORAGE_NOT_FOUND


def test_delete_notebook_cascade(tmp_path):
    conn = _migrated(tmp_path)
    rec = create_notebook(conn, name="X")
    delete_notebook(conn, rec.id)
    with pytest.raises(AppError):
        get_notebook(conn, rec.id)

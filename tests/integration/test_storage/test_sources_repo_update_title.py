import sqlite3

import pytest

from core.exceptions import AppError, ErrorCode
from core.storage import sources_repo
from core.storage.database import migrate


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    migrate(c)
    return c


def _nb(conn: sqlite3.Connection) -> str:
    from core.storage import notebooks_repo

    return notebooks_repo.create_notebook(conn, name="N").id


def test_update_source_title_sets_title_and_bumps_updated_at(conn):
    nb = _nb(conn)
    src = sources_repo.create_source(conn, notebook_id=nb, kind="recording", origin="録音")
    assert src.title is None

    updated = sources_repo.update_source_title(conn, src.id, "週次定例 RAG 改善")
    assert updated.title == "週次定例 RAG 改善"
    assert updated.id == src.id
    assert updated.updated_at >= src.updated_at


def test_update_source_title_unknown_id_raises_not_found(conn):
    with pytest.raises(AppError) as ei:
        sources_repo.update_source_title(conn, "does-not-exist", "x")
    assert ei.value.code == ErrorCode.STORAGE_NOT_FOUND

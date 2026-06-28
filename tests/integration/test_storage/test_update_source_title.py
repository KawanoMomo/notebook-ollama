"""update_source_title が title と updated_at のみを更新し、status は不変なことを検証。"""

import sqlite3

from core.storage import sources_repo
from core.storage.database import migrate
from core.storage.sources_repo import SourceStatus


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    migrate(c)
    c.execute(
        "INSERT INTO notebooks(id,name,created_at,updated_at) VALUES('nb','n','t','t')"
    )
    return c


def test_update_source_title_sets_title_keeps_status():
    conn = _conn()
    src = sources_repo.create_source(
        conn, notebook_id="nb", kind="recording", title=None, origin="録音"
    )
    sources_repo.update_source_status(
        conn, src.id, status=SourceStatus.READY
    )

    updated = sources_repo.update_source_title(conn, src.id, "来期予算レビュー")
    assert updated.title == "来期予算レビュー"
    # status は触らない。
    assert updated.status is SourceStatus.READY
    # updated_at は前進する。
    assert updated.updated_at >= src.updated_at
    # 永続化されている。
    assert sources_repo.get_source(conn, src.id).title == "来期予算レビュー"

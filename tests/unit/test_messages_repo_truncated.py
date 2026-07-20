"""truncated カラムの永続化(issue #22 自動継続)。"""
from __future__ import annotations

import sqlite3

import pytest

from core.storage import messages_repo, notebooks_repo
from core.storage.conversations_repo import create_conversation
from core.storage.database import migrate
from core.storage.migrations import run_message_truncated_migration


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    migrate(c)
    return c


def _make_conv(conn: sqlite3.Connection) -> str:
    nb = notebooks_repo.create_notebook(conn, name="N")
    conv = create_conversation(conn, notebook_id=nb.id)
    return conv.id


def test_append_message_persists_truncated(conn):
    conv_id = _make_conv(conn)
    m = messages_repo.append_message(
        conn, conversation_id=conv_id, role="assistant", content="途中",
        truncated=True,
    )
    assert m.truncated is True
    got = messages_repo.list_messages(conn, conversation_id=conv_id)
    assert got[-1].truncated is True


def test_update_message_content_replaces_and_clears_truncated(conn):
    conv_id = _make_conv(conn)
    m = messages_repo.append_message(
        conn, conversation_id=conv_id, role="assistant", content="途中",
        citations=[{"n": 1}], truncated=True,
    )
    updated = messages_repo.update_message_content(
        conn, message_id=m.id, content="途中と続き", citations=[{"n": 2}], truncated=False,
    )
    assert updated.content == "途中と続き"
    assert updated.citations == [{"n": 2}]
    assert updated.truncated is False


def test_truncated_migration_idempotent(conn):
    run_message_truncated_migration(conn)
    run_message_truncated_migration(conn)  # 2回目も例外なし
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(messages)")}
    assert "truncated" in cols

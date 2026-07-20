"""truncated カラムの永続化(issue #22 自動継続)。"""
from __future__ import annotations

import sqlite3

import pytest

from core.exceptions import AppError, ErrorCode
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


def test_update_message_content_not_found_raises_storage_not_found(conn):
    with pytest.raises(AppError) as exc_info:
        messages_repo.update_message_content(
            conn, message_id="does-not-exist", content="x", citations=None, truncated=False,
        )
    assert exc_info.value.code == ErrorCode.STORAGE_NOT_FOUND


def test_update_message_content_bumps_conversation_updated_at(conn):
    conv_id = _make_conv(conn)
    m = messages_repo.append_message(
        conn, conversation_id=conv_id, role="assistant", content="途中", truncated=True,
    )
    # 会話のupdated_atを意図的に古い値へ書き換えてから検証する
    # (ISOタイムスタンプの分解能に依存した比較によるflaky化を避けるため)
    conn.execute(
        "UPDATE conversations SET updated_at=? WHERE id=?",
        ("2000-01-01T00:00:00+00:00", conv_id),
    )
    messages_repo.update_message_content(
        conn, message_id=m.id, content="途中と続き", citations=None, truncated=False,
    )
    updated_at = conn.execute(
        "SELECT updated_at FROM conversations WHERE id=?", (conv_id,)
    ).fetchone()["updated_at"]
    assert updated_at != "2000-01-01T00:00:00+00:00"


def test_migration_adds_truncated_column_and_backfills_old_rows():
    """真のpre-migration経路: truncatedカラムが存在しないmessagesテーブルを持つ
    connを手書きCREATE TABLEで構築し、run_message_truncated_migration適用で
    カラムが追加されること、および旧row(truncated無しでINSERT済み)をmigration後に
    from_rowで読むとtruncated=FalseになりKeyErrorにならないことを確認する。"""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute(
        "CREATE TABLE messages ("
        "id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL, "
        "content TEXT NOT NULL, citations TEXT, model TEXT, created_at TEXT NOT NULL)"
    )
    c.execute(
        "INSERT INTO messages(id, conversation_id, role, content, citations, model, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("m1", "conv1", "assistant", "旧データ", None, None, "2020-01-01T00:00:00+00:00"),
    )

    cols_before = {r["name"] for r in c.execute("PRAGMA table_info(messages)")}
    assert "truncated" not in cols_before

    run_message_truncated_migration(c)

    cols_after = {r["name"] for r in c.execute("PRAGMA table_info(messages)")}
    assert "truncated" in cols_after

    row = c.execute("SELECT * FROM messages WHERE id=?", ("m1",)).fetchone()
    rec = messages_repo.MessageRecord.from_row(row)
    assert rec.truncated is False

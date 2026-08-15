from core.storage.conversations_repo import create_conversation
from core.storage.database import connect, migrate
from core.storage.messages_repo import append_message, get_message
from core.storage.notebooks_repo import create_notebook


def _ctx(tmp_path):
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    return conn, create_conversation(conn, notebook_id=nb.id, title="t")


def test_get_message_returns_record(tmp_path):
    conn, conv = _ctx(tmp_path)
    created = append_message(
        conn, conversation_id=conv.id, role="assistant", content="a[^1]", model="m"
    )
    got = get_message(conn, created.id)
    assert got is not None
    assert got.content == "a[^1]"
    assert got.conversation_id == conv.id


def test_get_message_returns_none_when_missing(tmp_path):
    conn, _ = _ctx(tmp_path)
    assert get_message(conn, "no-such-id") is None

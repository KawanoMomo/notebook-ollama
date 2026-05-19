from core.storage.conversations_repo import (
    create_conversation,
    get_conversation,
    list_conversations,
)
from core.storage.database import connect, migrate
from core.storage.messages_repo import (
    append_message,
    list_messages,
)
from core.storage.notebooks_repo import create_notebook


def _ctx(tmp_path):
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    return conn, nb


def test_create_conversation(tmp_path):
    conn, nb = _ctx(tmp_path)
    conv = create_conversation(conn, notebook_id=nb.id, title="t1")
    assert conv.title == "t1"
    fetched = get_conversation(conn, conv.id)
    assert fetched.id == conv.id


def test_list_conversations_filtered_by_notebook(tmp_path):
    conn, nb = _ctx(tmp_path)
    nb2 = create_notebook(conn, name="N2")
    a = create_conversation(conn, notebook_id=nb.id)
    create_conversation(conn, notebook_id=nb2.id)
    items = list_conversations(conn, notebook_id=nb.id)
    assert [c.id for c in items] == [a.id]


def test_append_and_list_messages(tmp_path):
    conn, nb = _ctx(tmp_path)
    conv = create_conversation(conn, notebook_id=nb.id)
    m1 = append_message(conn, conversation_id=conv.id, role="user", content="q1")
    m2 = append_message(
        conn,
        conversation_id=conv.id,
        role="assistant",
        content="a1",
        citations=[{"n": 1, "source_title": "x"}],
        model="qwen2.5:14b",
    )
    items = list_messages(conn, conversation_id=conv.id)
    assert [m.id for m in items] == [m1.id, m2.id]
    assert items[1].citations == [{"n": 1, "source_title": "x"}]
    assert items[1].model == "qwen2.5:14b"

"""source_markers repo — 録音タイムライン汎用マーカー(spec §4 案C)。"""
from __future__ import annotations

from core.storage.database import connect, migrate
from core.storage.notebooks_repo import create_notebook
from core.storage.source_markers_repo import MarkerRecord, insert_markers, list_markers
from core.storage.sources_repo import create_source


def _ctx(tmp_path):
    conn = connect(tmp_path / "meta.db")
    migrate(conn)
    nb = create_notebook(conn, name="nb")
    src = create_source(conn, notebook_id=nb.id, kind="recording", title="録音")
    return conn, src


def _mk(source_id, kind, value, at_ms):
    from core.ids import new_id
    return MarkerRecord(id=new_id(), source_id=source_id, kind=kind,
                        value=value, at_ms=at_ms)


def test_insert_and_list_sorted_by_at_ms(tmp_path):
    conn, src = _ctx(tmp_path)
    insert_markers(conn, [
        _mk(src.id, "page", "2", 5000),
        _mk(src.id, "page", "1", 0),
        _mk(src.id, "important", "x", 3000),
    ])
    all_markers = list_markers(conn, src.id)
    assert [m.at_ms for m in all_markers] == [0, 3000, 5000]
    pages = list_markers(conn, src.id, kind="page")
    assert [(m.value, m.at_ms) for m in pages] == [("1", 0), ("2", 5000)]


def test_list_markers_empty(tmp_path):
    conn, src = _ctx(tmp_path)
    assert list_markers(conn, src.id) == []


def test_source_delete_cascades_markers(tmp_path):
    conn, src = _ctx(tmp_path)
    insert_markers(conn, [_mk(src.id, "page", "1", 0)])
    conn.execute("DELETE FROM sources WHERE id = ?", (src.id,))
    assert list_markers(conn, src.id) == []

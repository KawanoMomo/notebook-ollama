"""source_links repo — 親子リンク汎用基盤(spec §4)。test_sources_repo.py の _ctx パターン踏襲。"""
from __future__ import annotations

import pytest

from core.exceptions import AppError
from core.storage.database import connect, migrate
from core.storage.notebooks_repo import create_notebook
from core.storage.source_links_repo import (
    get_parent_link,
    list_child_links,
    list_links_for_notebook,
    remove_parent,
    set_parent,
)
from core.storage.sources_repo import create_source


def _ctx(tmp_path):
    conn = connect(tmp_path / "meta.db")
    migrate(conn)
    nb = create_notebook(conn, name="nb")
    a = create_source(conn, notebook_id=nb.id, kind="pdf", title="資料A")
    b = create_source(conn, notebook_id=nb.id, kind="recording", title="録音B")
    c = create_source(conn, notebook_id=nb.id, kind="recording", title="録音C")
    return conn, nb, a, b, c


def test_set_parent_creates_link_with_meta(tmp_path):
    conn, nb, a, b, _ = _ctx(tmp_path)
    link = set_parent(
        conn, notebook_id=nb.id, parent_source_id=a.id, child_source_id=b.id,
        relation="presentation", meta={"presented_at": "2026-07-07"},
    )
    assert link.parent_source_id == a.id
    assert link.child_source_id == b.id
    assert link.relation == "presentation"
    assert link.meta == {"presented_at": "2026-07-07"}
    assert get_parent_link(conn, b.id).id == link.id


def test_set_parent_replaces_existing_parent(tmp_path):
    conn, nb, a, b, c = _ctx(tmp_path)
    set_parent(conn, notebook_id=nb.id, parent_source_id=a.id,
               child_source_id=b.id, relation="manual")
    set_parent(conn, notebook_id=nb.id, parent_source_id=c.id,
               child_source_id=b.id, relation="manual")
    assert get_parent_link(conn, b.id).parent_source_id == c.id
    assert list_child_links(conn, a.id) == []


def test_set_parent_rejects_self_link(tmp_path):
    conn, nb, a, _, _ = _ctx(tmp_path)
    with pytest.raises(AppError):
        set_parent(conn, notebook_id=nb.id, parent_source_id=a.id,
                   child_source_id=a.id, relation="manual")


def test_set_parent_rejects_cycle(tmp_path):
    conn, nb, a, b, c = _ctx(tmp_path)
    set_parent(conn, notebook_id=nb.id, parent_source_id=a.id,
               child_source_id=b.id, relation="manual")
    set_parent(conn, notebook_id=nb.id, parent_source_id=b.id,
               child_source_id=c.id, relation="manual")
    with pytest.raises(AppError):  # c を a の親にすると a→b→c→a の循環
        set_parent(conn, notebook_id=nb.id, parent_source_id=c.id,
                   child_source_id=a.id, relation="manual")


def test_remove_parent_and_list(tmp_path):
    conn, nb, a, b, c = _ctx(tmp_path)
    set_parent(conn, notebook_id=nb.id, parent_source_id=a.id,
               child_source_id=b.id, relation="presentation")
    set_parent(conn, notebook_id=nb.id, parent_source_id=a.id,
               child_source_id=c.id, relation="manual")
    assert len(list_links_for_notebook(conn, nb.id)) == 2
    assert len(list_child_links(conn, a.id)) == 2
    remove_parent(conn, b.id)
    assert get_parent_link(conn, b.id) is None
    assert len(list_links_for_notebook(conn, nb.id)) == 1


def test_source_delete_cascades_links(tmp_path):
    conn, nb, a, b, _ = _ctx(tmp_path)
    set_parent(conn, notebook_id=nb.id, parent_source_id=a.id,
               child_source_id=b.id, relation="presentation")
    conn.execute("DELETE FROM sources WHERE id = ?", (a.id,))
    assert get_parent_link(conn, b.id) is None

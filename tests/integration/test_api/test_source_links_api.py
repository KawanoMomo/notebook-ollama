"""手動リンク API (PUT/DELETE/GET)。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        yield c


def _nb(client):
    return client.post("/api/notebooks", json={"name": "nb"}).json()["id"]


def _upload(client, nb, name, data):
    """POST /api/notebooks/{id}/sources でファイルをアップロード、source ID を返す。"""
    r = client.post(
        f"/api/notebooks/{nb}/sources",
        files={"file": (name, data, "text/plain")},
    )
    assert r.status_code == 202, f"Upload failed: {r.status_code}, {r.text}"
    return r.json()["id"]


def test_set_and_list_and_remove_parent(client):
    """親設定 → 一覧 → 削除の正常系。"""
    nb = _nb(client)
    a = _upload(client, nb, "a.md", b"# a")
    b = _upload(client, nb, "b.md", b"# b")

    # PUT で親を設定
    r = client.put(
        f"/api/notebooks/{nb}/sources/{b}/parent",
        json={"parent_source_id": a},
    )
    assert r.status_code == 200
    link = r.json()
    assert link["relation"] == "manual"
    assert link["parent_source_id"] == a
    assert link["child_source_id"] == b

    # GET で一覧を確認
    links = client.get(f"/api/notebooks/{nb}/source-links").json()
    assert len(links) == 1
    assert links[0]["parent_source_id"] == a
    assert links[0]["child_source_id"] == b

    # DELETE で削除
    r = client.delete(f"/api/notebooks/{nb}/sources/{b}/parent")
    assert r.status_code == 204

    # GET で空になったことを確認
    links = client.get(f"/api/notebooks/{nb}/source-links").json()
    assert links == []


def test_self_and_cycle_rejected(client):
    """自己リンク・循環リンクは 400 を返す。"""
    nb = _nb(client)
    a = _upload(client, nb, "a.md", b"# a")
    b = _upload(client, nb, "b.md", b"# b")

    # 自己リンク: a を自分の親にしようとする
    r = client.put(
        f"/api/notebooks/{nb}/sources/{a}/parent",
        json={"parent_source_id": a},
    )
    assert r.status_code == 400

    # b の親を a に設定
    client.put(
        f"/api/notebooks/{nb}/sources/{b}/parent",
        json={"parent_source_id": a},
    )

    # 循環: a の親を b にしようとする (b -> a -> b になる)
    r = client.put(
        f"/api/notebooks/{nb}/sources/{a}/parent",
        json={"parent_source_id": b},
    )
    assert r.status_code == 400


def test_cross_notebook_rejected(client):
    """異なるノートブックのソース間でのリンク設定は 400 or 404 を返す。"""
    nb1 = _nb(client)
    nb2 = _nb(client)
    a = _upload(client, nb1, "a.md", b"# a")
    b = _upload(client, nb2, "b.md", b"# b")

    # nb2 のソース b の親を nb1 のソース a にしようとする
    r = client.put(
        f"/api/notebooks/{nb2}/sources/{b}/parent",
        json={"parent_source_id": a},
    )
    assert r.status_code in (400, 404)


def test_delete_non_existent_link_returns_204(client):
    """リンクが無いソースに DELETE すると 204 を返す(幕等性)。"""
    nb = _nb(client)
    a = _upload(client, nb, "a.md", b"# a")

    r = client.delete(f"/api/notebooks/{nb}/sources/{a}/parent")
    assert r.status_code == 204

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_create_list_get_update_delete_notebook(client):
    # create
    r = client.post("/api/notebooks", json={"name": "組み込み"})
    assert r.status_code == 201
    nb_id = r.json()["id"]

    # list
    r = client.get("/api/notebooks")
    assert r.status_code == 200
    items = r.json()
    assert any(n["id"] == nb_id for n in items)

    # get
    r = client.get(f"/api/notebooks/{nb_id}")
    assert r.status_code == 200
    assert r.json()["name"] == "組み込み"

    # update
    r = client.patch(f"/api/notebooks/{nb_id}", json={"default_model": "qwen2.5:14b"})
    assert r.status_code == 200
    assert r.json()["default_model"] == "qwen2.5:14b"

    # delete
    r = client.delete(f"/api/notebooks/{nb_id}")
    assert r.status_code == 204

    r = client.get(f"/api/notebooks/{nb_id}")
    assert r.status_code == 404


def test_create_notebook_validation_error(client):
    r = client.post("/api/notebooks", json={"name": ""})
    assert r.status_code == 422


def test_patch_clears_default_model_with_explicit_null(client):
    # まずモデルを設定
    r = client.post("/api/notebooks", json={"name": "N", "default_model": "qwen2.5:14b"})
    assert r.status_code == 201
    nb_id = r.json()["id"]
    assert r.json()["default_model"] == "qwen2.5:14b"

    # 明示 null でクリア(=全体既定に戻す)
    r = client.patch(f"/api/notebooks/{nb_id}", json={"default_model": None})
    assert r.status_code == 200
    assert r.json()["default_model"] is None

    # フィールド未指定では default_model を変えない(温存)
    r = client.patch(f"/api/notebooks/{nb_id}", json={"default_model": "llama3.1:8b"})
    assert r.status_code == 200
    r = client.patch(f"/api/notebooks/{nb_id}", json={"name": "N2"})
    assert r.status_code == 200
    assert r.json()["name"] == "N2"
    assert r.json()["default_model"] == "llama3.1:8b"


def test_delete_notebook_clears_visual_index(client):
    """回帰テスト: ノートブック削除が視覚索引に一切触れず、Qdrant のベクトルと
    visual_index_* の行が孤児として残っていた (issue #28 M5)。"""
    from core.storage.visual_index_repo import VisualIndexMeta, get_meta, upsert_meta

    nb_id = client.post("/api/notebooks", json={"name": "N"}).json()["id"]
    ctx = client.app.state.ctx
    for unit in ("page", "tile"):
        upsert_meta(
            ctx.conn,
            VisualIndexMeta(
                notebook_id=nb_id, unit=unit,
                embedding_model="m", built_at="2026-08-02T00:00:00+00:00",
            ),
        )
    assert get_meta(ctx.conn, nb_id, "page") is not None
    assert get_meta(ctx.conn, nb_id, "tile") is not None

    deleted: list[tuple[str, str]] = []
    ctx.visual_stores = {
        u: type("S", (), {"delete_by_notebook": staticmethod(
            lambda n, _u=u: deleted.append((_u, n))
        )})()
        for u in ("page", "tile")
    }

    assert client.delete(f"/api/notebooks/{nb_id}").status_code == 204
    assert get_meta(ctx.conn, nb_id, "page") is None
    assert get_meta(ctx.conn, nb_id, "tile") is None
    assert sorted(deleted) == [("page", nb_id), ("tile", nb_id)]


def test_delete_notebook_survives_visual_cleanup_failure(client):
    """掃除が失敗してもノートブック本体の削除は通ること (残骸より本体を優先)。"""
    nb_id = client.post("/api/notebooks", json={"name": "N"}).json()["id"]
    ctx = client.app.state.ctx

    def _boom(_n):
        raise RuntimeError("qdrant down")

    ctx.visual_stores = {"page": type("S", (), {"delete_by_notebook": staticmethod(_boom)})()}
    assert client.delete(f"/api/notebooks/{nb_id}").status_code == 204
    assert client.get(f"/api/notebooks/{nb_id}").status_code == 404

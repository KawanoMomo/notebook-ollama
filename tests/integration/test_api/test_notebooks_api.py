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

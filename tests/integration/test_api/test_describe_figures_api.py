from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        yield c


def _create_nb(client) -> str:
    return client.post("/api/notebooks", json={"name": "N"}).json()["id"]


def _enable_beta(client, enabled: bool = True) -> None:
    client.put("/api/features/table-figure-rag", json={"enabled": enabled})


def _upload_pdf(client, nb) -> str:
    files = {"file": ("t.pdf", io.BytesIO(b"%PDF-1.4\n%fake"), "application/pdf")}
    r = client.post(f"/api/notebooks/{nb}/sources", files=files)
    assert r.status_code == 202, r.text
    return r.json()["id"]


def test_describe_figures_403_when_beta_off(client):
    nb = _create_nb(client)
    sid = _upload_pdf(client, nb)
    _enable_beta(client, False)
    res = client.post(f"/api/notebooks/{nb}/sources/{sid}/describe-figures")
    assert res.status_code == 403


def test_describe_figures_202_when_beta_on(client):
    nb = _create_nb(client)
    sid = _upload_pdf(client, nb)
    _enable_beta(client, True)
    res = client.post(f"/api/notebooks/{nb}/sources/{sid}/describe-figures")
    assert res.status_code == 202


def test_get_asset_image_403_when_beta_off(client):
    nb = _create_nb(client)
    sid = _upload_pdf(client, nb)
    _enable_beta(client, False)
    res = client.get(f"/api/notebooks/{nb}/sources/{sid}/assets/nonexistent-asset")
    assert res.status_code == 403


def test_get_asset_image_404_when_asset_missing(client):
    nb = _create_nb(client)
    sid = _upload_pdf(client, nb)
    _enable_beta(client, True)
    res = client.get(f"/api/notebooks/{nb}/sources/{sid}/assets/nonexistent-asset")
    assert res.status_code == 404

"""スライド配信APIとhas_slides(spec §5)。"""
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


def test_pdf_source_serves_slides_and_has_slides_true(client):
    nb = _nb(client)
    r = client.post(
        f"/api/notebooks/{nb}/sources",
        files={"file": ("deck.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    sid = r.json()["id"]

    r = client.get(f"/api/notebooks/{nb}/sources/{sid}/slides")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content.startswith(b"%PDF")

    listed = client.get(f"/api/notebooks/{nb}/sources").json()
    me = next(s for s in listed if s["id"] == sid)
    assert me["has_slides"] is True


def test_pptx_without_conversion_404_and_has_slides_false(client, tmp_path, monkeypatch):
    # COM変換をno-opにして「変換されなかったPPTX」を再現(実PowerPoint起動も禁止)
    import apps.api.routers.sources as sources_mod
    monkeypatch.setattr(sources_mod, "_convert_slides_best_effort",
                        lambda *a, **k: None, raising=False)
    nb = _nb(client)
    r = client.post(
        f"/api/notebooks/{nb}/sources",
        files={"file": ("deck.pptx", b"PK fake pptx",
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
    )
    sid = r.json()["id"]

    assert client.get(f"/api/notebooks/{nb}/sources/{sid}/slides").status_code == 404
    listed = client.get(f"/api/notebooks/{nb}/sources").json()
    me = next(s for s in listed if s["id"] == sid)
    assert me["has_slides"] is False


def test_non_slide_source_404(client):
    nb = _nb(client)
    r = client.post(
        f"/api/notebooks/{nb}/sources",
        files={"file": ("note.md", b"# hi", "text/markdown")},
    )
    sid = r.json()["id"]
    assert client.get(f"/api/notebooks/{nb}/sources/{sid}/slides").status_code == 404

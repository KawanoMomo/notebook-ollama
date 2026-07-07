"""マーカー記録API + active照会(spec §6)。test_recordings_api.py の fake 注入パターン踏襲。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


class _FakeRecorder:
    def __init__(self, session_dir):
        self.session_dir = session_dir

    def start(self, **kwargs):
        pass

    def stop(self):
        return {"mic": None, "system": None}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        c.app.state.ctx.recorder_factory = lambda session_dir: _FakeRecorder(session_dir)
        c.app.state.ctx.transcriber_factory = lambda: None
        c.app.state.ctx.diarizer_factory = lambda: None
        yield c


def _make_notebook(client) -> str:
    r = client.post("/api/notebooks", json={"name": "nb"})
    return r.json()["id"]


def _upload_pdf(client, nb: str) -> str:
    # 最小の正当な擬似PDFバイト列(パースは background なので内容は問わない)。
    # 実際のアップロードルートは /api/notebooks/{nb}/sources (202, multipart "file")。
    r = client.post(
        f"/api/notebooks/{nb}/sources",
        files={"file": ("slides.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert r.status_code == 202, r.text
    return r.json()["id"]


def _start(client, nb: str, presentation_source_id: str | None = None):
    body: dict = {"live_caption": False}
    if presentation_source_id is not None:
        body["presentation_source_id"] = presentation_source_id
    return client.post(f"/api/notebooks/{nb}/recordings", json=body)


def test_marker_records_at_ms_on_server_timeline(client):
    nb = _make_notebook(client)
    rid = _start(client, nb).json()["recording_id"]

    r = client.post(
        f"/api/notebooks/{nb}/recordings/{rid}/markers",
        json={"kind": "page", "value": "1"},
    )
    assert r.status_code == 200
    at1 = r.json()["at_ms"]
    assert at1 >= 0

    r = client.post(
        f"/api/notebooks/{nb}/recordings/{rid}/markers",
        json={"kind": "page", "value": "2"},
    )
    assert r.json()["at_ms"] >= at1


def test_marker_unknown_recording_404(client):
    nb = _make_notebook(client)
    r = client.post(
        f"/api/notebooks/{nb}/recordings/nonexistent/markers",
        json={"kind": "page", "value": "1"},
    )
    assert r.status_code == 404


def test_start_with_presentation_source_validates_kind(client):
    nb = _make_notebook(client)
    pdf_id = _upload_pdf(client, nb)

    r = _start(client, nb, presentation_source_id=pdf_id)
    assert r.status_code == 200

    # 停止して次のテストに備える
    rid = r.json()["recording_id"]
    client.post(f"/api/notebooks/{nb}/recordings/{rid}/stop")


def test_start_with_unknown_presentation_source_400(client):
    nb = _make_notebook(client)
    r = _start(client, nb, presentation_source_id="no-such-source")
    assert r.status_code in (400, 404)


def test_page_marker_rejects_non_numeric_value(client):
    """kind=page の非数値 value は 422。以降の active 照会が 500 にならないこと。"""
    nb = _make_notebook(client)
    rid = _start(client, nb).json()["recording_id"]

    r = client.post(
        f"/api/notebooks/{nb}/recordings/{rid}/markers",
        json={"kind": "page", "value": "abc"},
    )
    assert r.status_code == 422

    # リロード復帰用エンドポイントはクラッシュしない(500 禁止)
    r = client.get(f"/api/notebooks/{nb}/recordings/active")
    assert r.status_code == 200
    assert r.json()["last_page"] is None

    # 正常マーカー後は last_page が復活する
    client.post(
        f"/api/notebooks/{nb}/recordings/{rid}/markers",
        json={"kind": "page", "value": "7"},
    )
    r = client.get(f"/api/notebooks/{nb}/recordings/active")
    assert r.status_code == 200
    assert r.json()["last_page"] == 7


def test_page_marker_rejects_unicode_digit_422(client):
    """'³' は str.isdigit() を通すが int() が拒む。isdigit ゲートでは素通りして
    永続化され、pipeline のページ割当を落とすため int-parse 基準で 422 に弾く。"""
    nb = _make_notebook(client)
    rid = _start(client, nb).json()["recording_id"]

    r = client.post(
        f"/api/notebooks/{nb}/recordings/{rid}/markers",
        json={"kind": "page", "value": "³"},
    )
    assert r.status_code == 422


def test_add_marker_cross_notebook_404(client):
    """別ノートブックの notebook_id 経由では既存 rid にマーカーを打てない。"""
    nb = _make_notebook(client)
    other_nb = _make_notebook(client)
    rid = _start(client, nb).json()["recording_id"]

    r = client.post(
        f"/api/notebooks/{other_nb}/recordings/{rid}/markers",
        json={"kind": "page", "value": "1"},
    )
    assert r.status_code == 404


def test_active_returns_session_info_and_last_page(client):
    nb = _make_notebook(client)
    pdf_id = _upload_pdf(client, nb)

    r = client.get(f"/api/notebooks/{nb}/recordings/active")
    assert r.status_code == 204

    start = _start(client, nb, presentation_source_id=pdf_id).json()
    rid = start["recording_id"]
    client.post(f"/api/notebooks/{nb}/recordings/{rid}/markers",
                json={"kind": "page", "value": "1"})
    client.post(f"/api/notebooks/{nb}/recordings/{rid}/markers",
                json={"kind": "page", "value": "4"})

    r = client.get(f"/api/notebooks/{nb}/recordings/active")
    assert r.status_code == 200
    body = r.json()
    assert body["recording_id"] == rid
    assert body["source_id"] == start["source_id"]
    assert body["presentation_source_id"] == pdf_id
    assert body["last_page"] == 4
    # リロード復帰用の経過時間(recordingStore.adopt がタイマー再開に使う)
    assert body["elapsed_ms"] >= 0

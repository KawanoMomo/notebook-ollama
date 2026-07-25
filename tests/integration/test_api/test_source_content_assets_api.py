"""GET .../content が表アセット抽出(ベータ機能)と整合すること。

get_source_content は chunks テーブルを使わず、原本ファイルを都度再パースする
既存エンドポイント(Stage 1 以前から存在)。ベータ ON の PDF ソースでは
chunk 本文(GET .../chunks/{id})と同じ Markdown 表が section.text に
埋め込まれる必要がある(FE の section.text 全文置換ロジックが一致点を
見つけられるように)。ベータ OFF なら従来どおりのフラットテキストのまま。
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

pymupdf = pytest.importorskip("pymupdf")
pytestmark = pytest.mark.pdf

from apps.api.main import create_app  # noqa: E402
from tests.unit.fixtures_pdf import build_pdf_with_table  # noqa: E402

ROWS = [["品名", "数量"], ["ネジ", "10"]]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        ctx = c.app.state.ctx

        class NoopPipeline:
            async def run(self, *, source_id, kind, data):
                from core.storage.sources_repo import SourceStatus, update_source_status

                update_source_status(ctx.conn, source_id, status=SourceStatus.READY, chunk_count=0)

        ctx.pipeline = NoopPipeline()
        yield c


def _create_nb(client) -> str:
    return client.post("/api/notebooks", json={"name": "N"}).json()["id"]


def _enable_beta(client, enabled: bool) -> None:
    client.put("/api/features/table-figure-rag", json={"enabled": enabled})


def _upload_pdf_with_table(client, nb) -> str:
    files = {"file": ("t.pdf", io.BytesIO(build_pdf_with_table(ROWS)), "application/pdf")}
    r = client.post(f"/api/notebooks/{nb}/sources", files=files)
    assert r.status_code == 202, r.text
    return r.json()["id"]


def test_content_includes_markdown_table_when_beta_on(client):
    nb = _create_nb(client)
    _enable_beta(client, True)
    sid = _upload_pdf_with_table(client, nb)

    r = client.get(f"/api/notebooks/{nb}/sources/{sid}/content")
    assert r.status_code == 200, r.text
    texts = [s["text"] for s in r.json()["sections"]]
    assert any("| 品名 | 数量 |" in t for t in texts)


def test_content_excludes_markdown_table_when_beta_off(client):
    nb = _create_nb(client)
    _enable_beta(client, False)
    sid = _upload_pdf_with_table(client, nb)

    r = client.get(f"/api/notebooks/{nb}/sources/{sid}/content")
    assert r.status_code == 200, r.text
    texts = [s["text"] for s in r.json()["sections"]]
    assert not any("| 品名 | 数量 |" in t for t in texts)


def _scanned_pdf_bytes() -> bytes:
    """テキストレイヤーを一切持たない(画像のみの)PDFを合成する。"""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    pm = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 500), False)
    pm.set_rect(pm.irect, (255, 255, 255))
    page.insert_image(pymupdf.Rect(0, 0, 595, 842), pixmap=pm)
    data = doc.tobytes()
    doc.close()
    return data


def _upload_scanned_pdf(client, nb) -> str:
    files = {"file": ("scan.pdf", io.BytesIO(_scanned_pdf_bytes()), "application/pdf")}
    r = client.post(f"/api/notebooks/{nb}/sources", files=files)
    assert r.status_code == 202, r.text
    return r.json()["id"]


def test_scanned_pdf_content_served_from_stored_chunks_without_reocr(client):
    """回帰テスト: get_source_content がスキャンPDFの閲覧のたびに全ページを
    再OCRしていた(VLM呼び出しは1ページ数十秒+グローバルchatロック占有。
    さらにOCR経路構築がベータフラグを見ておらず spec のOFF挙動にも違反)。
    修正後: 取込時にOCR済みの本文チャンクをそのまま返す(VLM呼び出しゼロ)。"""
    from core.storage.chunks_repo import ChunkRecord, insert_chunks

    nb = _create_nb(client)
    _enable_beta(client, True)
    sid = _upload_scanned_pdf(client, nb)
    ctx = client.app.state.ctx
    # 取込時OCRの成果物に相当するチャンクを直接投入(text + figure_desc)
    insert_chunks(ctx.conn, [
        ChunkRecord(
            id="c" * 26, source_id=sid, notebook_id=nb, ord=0, page=1,
            heading_path=None, text="OCRで書き起こした本文です。", token_count=10,
        ),
        ChunkRecord(
            id="d" * 26, source_id=sid, notebook_id=nb, ord=1, page=1,
            heading_path=None, text="図の説明チャンク", token_count=4, kind="figure_desc",
        ),
    ])

    r = client.get(f"/api/notebooks/{nb}/sources/{sid}/content")
    assert r.status_code == 200, r.text
    texts = [s["text"] for s in r.json()["sections"]]
    assert texts == ["OCRで書き起こした本文です。"]  # figure_desc は本文ビューに出さない


def test_scanned_pdf_content_without_chunks_errors_as_before(client):
    """スキャンPDFで取込済みチャンクも無い場合は従来どおりエラー(再OCRしない)。"""
    nb = _create_nb(client)
    _enable_beta(client, True)
    sid = _upload_scanned_pdf(client, nb)

    r = client.get(f"/api/notebooks/{nb}/sources/{sid}/content")
    assert r.status_code != 200

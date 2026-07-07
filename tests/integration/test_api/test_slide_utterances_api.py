"""スライド資料からの発言逆引き API(spec §7, Task 11)。

`GET /api/notebooks/{nid}/sources/{sid}/slide-utterances` — sid はスライド資料
(pdf/pptx)の親ソース。source_links で子(全 relation)を辿り、各子の
list_chunks_for_source から page が非 NULL のチャンクをページ昇順にグループ化して
返す。子ゼロ/該当チャンクゼロは []。sid が pdf/pptx 以外なら 400。
"""
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


def test_slide_utterances_groups_by_page_ascending(client):
    """子録音2ソース・page付きチャンク3件/2ページ → page昇順グループ、items は

    (child_source_id, start_ms) 順。
    """
    nb = _nb(client)
    ctx = client.app.state.ctx
    from core.storage.chunks_repo import ChunkRecord, insert_chunks
    from core.storage.source_links_repo import set_parent
    from core.storage.sources_repo import create_source

    parent = create_source(
        ctx.conn, notebook_id=nb, kind="pdf", origin="deck.pdf",
        title="資料A", content_hash="parent1",
    )
    rec1 = create_source(
        ctx.conn, notebook_id=nb, kind="recording", origin="talk1.mp3",
        title="録音1", content_hash="rec1",
    )
    rec2 = create_source(
        ctx.conn, notebook_id=nb, kind="recording", origin="talk2.mp3",
        title="録音2", content_hash="rec2",
    )
    set_parent(
        ctx.conn, notebook_id=nb, parent_source_id=parent.id,
        child_source_id=rec1.id, relation="presentation",
    )
    set_parent(
        ctx.conn, notebook_id=nb, parent_source_id=parent.id,
        child_source_id=rec2.id, relation="presentation",
    )

    insert_chunks(ctx.conn, [
        ChunkRecord(id="a" * 26, source_id=rec1.id, notebook_id=nb, ord=0,
                    page=2, heading_path=None, text="page2 rec1", token_count=1,
                    start_ms=1000, end_ms=2000, speaker="あなた"),
        ChunkRecord(id="b" * 26, source_id=rec2.id, notebook_id=nb, ord=0,
                    page=1, heading_path=None, text="page1 rec2", token_count=1,
                    start_ms=500, end_ms=1500, speaker="相手1"),
        ChunkRecord(id="c" * 26, source_id=rec1.id, notebook_id=nb, ord=1,
                    page=1, heading_path=None, text="page1 rec1", token_count=1,
                    start_ms=0, end_ms=500, speaker="あなた"),
    ])

    r = client.get(f"/api/notebooks/{nb}/sources/{parent.id}/slide-utterances")
    assert r.status_code == 200
    body = r.json()

    # page 昇順のグループ形状
    assert [g["page"] for g in body] == [1, 2]

    page1 = next(g for g in body if g["page"] == 1)
    page2 = next(g for g in body if g["page"] == 2)
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 1

    # items は (child_source_id, start_ms) 順
    expected_child_order = sorted([rec1.id, rec2.id])
    assert [it["child_source_id"] for it in page1["items"]] == expected_child_order

    # レスポンス形状(全フィールド)
    item = page2["items"][0]
    assert item == {
        "child_source_id": rec1.id,
        "child_title": "録音1",
        "chunk_id": "a" * 26,
        "start_ms": 1000,
        "end_ms": 2000,
        "speaker": "あなた",
        "text": "page2 rec1",
    }


def test_slide_utterances_excludes_non_recording_children(client):
    """録音以外の子(手動リンクの PDF 子など)は逆引き対象外。

    手動リンク UI は任意ソースを子にできるため、PDF 親に PDF 子をリンクすると
    文書チャンク(page 非null・start_ms/speaker は None)が偽の「発言」として
    混入しうる。契約は「child(kind=recording)を辿り」— 録音子の items のみ返す。
    """
    nb = _nb(client)
    ctx = client.app.state.ctx
    from core.storage.chunks_repo import ChunkRecord, insert_chunks
    from core.storage.source_links_repo import set_parent
    from core.storage.sources_repo import create_source

    parent = create_source(
        ctx.conn, notebook_id=nb, kind="pdf", origin="deck.pdf",
        title="資料A", content_hash="parent_mixed",
    )
    rec = create_source(
        ctx.conn, notebook_id=nb, kind="recording", origin="talk.mp3",
        title="録音1", content_hash="rec_mixed",
    )
    pdf_child = create_source(
        ctx.conn, notebook_id=nb, kind="pdf", origin="appendix.pdf",
        title="別紙PDF", content_hash="pdf_child_mixed",
    )
    set_parent(
        ctx.conn, notebook_id=nb, parent_source_id=parent.id,
        child_source_id=rec.id, relation="presentation",
    )
    set_parent(
        ctx.conn, notebook_id=nb, parent_source_id=parent.id,
        child_source_id=pdf_child.id, relation="manual",
    )

    insert_chunks(ctx.conn, [
        # 録音子: 正当な「発言」
        ChunkRecord(id="d" * 26, source_id=rec.id, notebook_id=nb, ord=0,
                    page=1, heading_path=None, text="録音の発言", token_count=1,
                    start_ms=0, end_ms=1000, speaker="あなた"),
        # PDF 子: page 付き文書チャンク(start_ms/speaker は None)— 混入してはならない
        ChunkRecord(id="e" * 26, source_id=pdf_child.id, notebook_id=nb, ord=0,
                    page=1, heading_path="第1章", text="文書本文", token_count=1,
                    start_ms=None, end_ms=None, speaker=None),
        ChunkRecord(id="f" * 26, source_id=pdf_child.id, notebook_id=nb, ord=1,
                    page=2, heading_path="第2章", text="文書本文2", token_count=1,
                    start_ms=None, end_ms=None, speaker=None),
    ])

    r = client.get(f"/api/notebooks/{nb}/sources/{parent.id}/slide-utterances")
    assert r.status_code == 200
    body = r.json()

    # 録音子の items のみ: PDF 子由来の page=2 グループも項目も存在しない
    assert [g["page"] for g in body] == [1]
    items = body[0]["items"]
    assert [it["chunk_id"] for it in items] == ["d" * 26]
    assert all(it["child_source_id"] == rec.id for it in items)


def test_slide_utterances_no_children_returns_empty_list(client):
    """子リンクが無いスライド資料は [] を返す。"""
    nb = _nb(client)
    ctx = client.app.state.ctx
    from core.storage.sources_repo import create_source

    parent = create_source(
        ctx.conn, notebook_id=nb, kind="pdf", origin="deck.pdf",
        title="資料B", content_hash="parent2",
    )

    r = client.get(f"/api/notebooks/{nb}/sources/{parent.id}/slide-utterances")
    assert r.status_code == 200
    assert r.json() == []


def test_slide_utterances_on_recording_source_400(client):
    """録音ソースに対する呼び出しは 400(sid はスライド資料 pdf/pptx のみ)。"""
    nb = _nb(client)
    ctx = client.app.state.ctx
    from core.storage.sources_repo import create_source

    rec = create_source(
        ctx.conn, notebook_id=nb, kind="recording", origin="talk.mp3",
        content_hash="rec_only",
    )

    r = client.get(f"/api/notebooks/{nb}/sources/{rec.id}/slide-utterances")
    assert r.status_code == 400

import io

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    # patch the ingestion pipeline to a no-op so we don't need Ollama
    with TestClient(app) as c:
        ctx = c.app.state.ctx

        class NoopPipeline:
            async def run(self, *, source_id, kind, data):
                from core.storage.sources_repo import SourceStatus, update_source_status

                update_source_status(ctx.conn, source_id, status=SourceStatus.READY, chunk_count=0)

        ctx.pipeline = NoopPipeline()
        yield c


def _create_nb(client, name="N") -> str:
    r = client.post("/api/notebooks", json={"name": name})
    return r.json()["id"]


def _create_recording(client, nb) -> str:
    from core.storage import sources_repo

    ctx = client.app.state.ctx
    src = sources_repo.create_source(
        ctx.conn, notebook_id=nb, kind="recording", title=None, origin="録音"
    )
    return src.id


def test_upload_markdown_source(client):
    nb = _create_nb(client)
    files = {"file": ("hello.md", io.BytesIO(b"# Hello\n\nbody."), "text/markdown")}
    r = client.post(f"/api/notebooks/{nb}/sources", files=files)
    assert r.status_code == 202
    body = r.json()
    assert body["status"] in {"pending", "ready"}


def test_upload_unsupported_kind_returns_400(client):
    nb = _create_nb(client)
    files = {"file": ("hello.bin", io.BytesIO(b"\x00\x01"), "application/octet-stream")}
    r = client.post(f"/api/notebooks/{nb}/sources", files=files)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "ingestion.unsupported_kind"


def test_list_sources(client):
    nb = _create_nb(client)
    files = {"file": ("a.md", io.BytesIO(b"# A"), "text/markdown")}
    client.post(f"/api/notebooks/{nb}/sources", files=files)
    r = client.get(f"/api/notebooks/{nb}/sources")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_delete_source(client):
    nb = _create_nb(client)
    files = {"file": ("a.md", io.BytesIO(b"# A"), "text/markdown")}
    r = client.post(f"/api/notebooks/{nb}/sources", files=files)
    sid = r.json()["id"]
    r = client.delete(f"/api/notebooks/{nb}/sources/{sid}")
    assert r.status_code == 204


def test_retry_source_with_saved_bytes(client):
    nb = _create_nb(client)
    files = {"file": ("hello.md", io.BytesIO(b"# Hello\n\nbody."), "text/markdown")}
    r = client.post(f"/api/notebooks/{nb}/sources", files=files)
    sid = r.json()["id"]
    # mark as error to exercise retry path
    from core.storage.sources_repo import SourceStatus, update_source_status
    ctx = client.app.state.ctx
    update_source_status(ctx.conn, sid, status=SourceStatus.ERROR, error_msg="forced")
    r = client.post(f"/api/notebooks/{nb}/sources/{sid}/retry")
    assert r.status_code == 200
    assert r.json()["status"] in {"pending", "ready"}


def test_retry_source_missing_bytes_returns_400(client, tmp_path):
    nb = _create_nb(client)
    files = {"file": ("hello.md", io.BytesIO(b"# X"), "text/markdown")}
    r = client.post(f"/api/notebooks/{nb}/sources", files=files)
    sid = r.json()["id"]
    # delete the saved bytes manually
    ctx = client.app.state.ctx
    from pathlib import Path
    for p in Path(ctx.config.sources_dir).glob(f"{sid}.*"):
        p.unlink()
    r = client.post(f"/api/notebooks/{nb}/sources/{sid}/retry")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "input.invalid"


def test_get_chunk_returns_chunk_text(client):
    nb = _create_nb(client)
    files = {"file": ("hello.md", io.BytesIO(b"# Hello\n\nbody."), "text/markdown")}
    r = client.post(f"/api/notebooks/{nb}/sources", files=files)
    sid = r.json()["id"]
    # the no-op pipeline created 0 chunks; manually insert a chunk
    ctx = client.app.state.ctx
    from core.storage.chunks_repo import ChunkRecord, insert_chunks
    chunk = ChunkRecord(
        id="0" * 26, source_id=sid, notebook_id=nb,
        ord=0, page=1, heading_path="h", text="hello chunk", token_count=2,
    )
    insert_chunks(ctx.conn, [chunk])
    r = client.get(f"/api/notebooks/{nb}/sources/{sid}/chunks/{chunk.id}")
    assert r.status_code == 200
    assert r.json()["text"] == "hello chunk"


def _insert_chunk(ctx, *, cid, sid, nb, ord_, speaker):
    from core.storage.chunks_repo import ChunkRecord, insert_chunks

    insert_chunks(
        ctx.conn,
        [
            ChunkRecord(
                id=cid, source_id=sid, notebook_id=nb,
                ord=ord_, page=None, heading_path=None,
                text=f"text {ord_}", token_count=2, speaker=speaker,
            )
        ],
    )


def test_rename_speaker_updates_all_chunks_of_label(client):
    """同一話者ラベルの全チャンクを一括更新し件数を返す。"""
    nb = _create_nb(client)
    sid = _create_recording(client, nb)
    ctx = client.app.state.ctx
    _insert_chunk(ctx, cid="c0", sid=sid, nb=nb, ord_=0, speaker="相手1")
    _insert_chunk(ctx, cid="c1", sid=sid, nb=nb, ord_=1, speaker="相手1")
    _insert_chunk(ctx, cid="c2", sid=sid, nb=nb, ord_=2, speaker="相手1")

    r = client.patch(
        f"/api/notebooks/{nb}/sources/{sid}/speaker",
        json={"from_label": "相手1", "to_label": "田中さん"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 3

    rows = ctx.conn.execute(
        "SELECT speaker FROM chunks WHERE source_id = ? ORDER BY ord", (sid,)
    ).fetchall()
    assert [row["speaker"] for row in rows] == ["田中さん", "田中さん", "田中さん"]


def test_rename_speaker_leaves_other_speakers_untouched(client):
    """同 source 内の別話者は変更しない。"""
    nb = _create_nb(client)
    sid = _create_recording(client, nb)
    ctx = client.app.state.ctx
    _insert_chunk(ctx, cid="c0", sid=sid, nb=nb, ord_=0, speaker="相手1")
    _insert_chunk(ctx, cid="c1", sid=sid, nb=nb, ord_=1, speaker="あなた")

    r = client.patch(
        f"/api/notebooks/{nb}/sources/{sid}/speaker",
        json={"from_label": "相手1", "to_label": "田中さん"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 1

    rows = ctx.conn.execute(
        "SELECT speaker FROM chunks WHERE source_id = ? ORDER BY ord", (sid,)
    ).fetchall()
    assert [row["speaker"] for row in rows] == ["田中さん", "あなた"]


def test_rename_speaker_scoped_within_source(client):
    """別 source の同名ラベルは変更しない(スコープ = source 内)。"""
    nb = _create_nb(client)
    sid = _create_recording(client, nb)
    other = _create_recording(client, nb)
    ctx = client.app.state.ctx
    _insert_chunk(ctx, cid="a0", sid=sid, nb=nb, ord_=0, speaker="相手1")
    _insert_chunk(ctx, cid="b0", sid=other, nb=nb, ord_=0, speaker="相手1")

    r = client.patch(
        f"/api/notebooks/{nb}/sources/{sid}/speaker",
        json={"from_label": "相手1", "to_label": "田中さん"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 1

    other_speaker = ctx.conn.execute(
        "SELECT speaker FROM chunks WHERE source_id = ?", (other,)
    ).fetchone()["speaker"]
    assert other_speaker == "相手1"


def test_rename_speaker_empty_to_label_returns_400(client):
    nb = _create_nb(client)
    sid = _create_recording(client, nb)
    r = client.patch(
        f"/api/notebooks/{nb}/sources/{sid}/speaker",
        json={"from_label": "相手1", "to_label": "   "},
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "input.invalid"


def test_rename_speaker_unknown_from_label_returns_zero(client):
    nb = _create_nb(client)
    sid = _create_recording(client, nb)
    ctx = client.app.state.ctx
    _insert_chunk(ctx, cid="c0", sid=sid, nb=nb, ord_=0, speaker="相手1")
    r = client.patch(
        f"/api/notebooks/{nb}/sources/{sid}/speaker",
        json={"from_label": "存在しない", "to_label": "田中さん"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 0


def test_rename_speaker_cross_notebook_returns_404(client):
    nb_a = _create_nb(client, "A")
    nb_b = _create_nb(client, "B")
    sid = _create_recording(client, nb_a)
    r = client.patch(
        f"/api/notebooks/{nb_b}/sources/{sid}/speaker",
        json={"from_label": "相手1", "to_label": "田中さん"},
    )
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "storage.not_found"


def test_delete_recording_source_removes_audio_dir(client):
    """録音ソース削除時、音声ディレクトリ (sources_dir/<id>/) ごと消す。"""
    nb = _create_nb(client)
    ctx = client.app.state.ctx
    from core.storage import sources_repo

    src = sources_repo.create_source(
        ctx.conn, notebook_id=nb, kind="recording", title=None, origin="録音"
    )
    rec_dir = ctx.config.sources_dir / src.id
    rec_dir.mkdir(parents=True, exist_ok=True)
    (rec_dir / "mic.m4a").write_bytes(b"audio-bytes")
    (rec_dir / "system.wav").write_bytes(b"x" * 44)
    assert rec_dir.is_dir()

    r = client.delete(f"/api/notebooks/{nb}/sources/{src.id}")
    assert r.status_code == 204
    assert not rec_dir.exists()

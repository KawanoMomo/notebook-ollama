import pytest
from core.exceptions import AppError, ErrorCode
from core.storage.database import connect, migrate
from core.storage.notebooks_repo import create_notebook
from core.storage.sources_repo import (
    SourceRecord,
    SourceStatus,
    create_source,
    get_source,
    list_sources,
    update_source_status,
    upsert_dedupe,
)

def _ctx(tmp_path):
    conn = connect(tmp_path / "metadata.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    return conn, nb

def test_create_source_pending(tmp_path):
    conn, nb = _ctx(tmp_path)
    rec = create_source(
        conn,
        notebook_id=nb.id,
        kind="pdf",
        title="ARM Cortex-M4",
        origin="arm.pdf",
        content_hash="abc123",
        bytes_=1234,
    )
    assert rec.status == SourceStatus.PENDING
    assert rec.id and len(rec.id) == 26

def test_list_sources_by_notebook(tmp_path):
    conn, nb = _ctx(tmp_path)
    a = create_source(conn, notebook_id=nb.id, kind="md", origin="a.md", content_hash="h1")
    b = create_source(conn, notebook_id=nb.id, kind="md", origin="b.md", content_hash="h2")
    items = list_sources(conn, notebook_id=nb.id)
    ids = {s.id for s in items}
    assert ids == {a.id, b.id}

def test_update_source_status_to_ready_with_counts(tmp_path):
    conn, nb = _ctx(tmp_path)
    rec = create_source(conn, notebook_id=nb.id, kind="md", origin="a.md", content_hash="h1")
    update_source_status(conn, rec.id, status=SourceStatus.READY, page_count=10, chunk_count=23)
    refreshed = get_source(conn, rec.id)
    assert refreshed.status == SourceStatus.READY
    assert refreshed.page_count == 10
    assert refreshed.chunk_count == 23

def test_update_source_status_to_error_records_message(tmp_path):
    conn, nb = _ctx(tmp_path)
    rec = create_source(conn, notebook_id=nb.id, kind="pdf", origin="a.pdf", content_hash="h")
    update_source_status(conn, rec.id, status=SourceStatus.ERROR, error_msg="parse failed")
    refreshed = get_source(conn, rec.id)
    assert refreshed.status == SourceStatus.ERROR
    assert refreshed.error_msg == "parse failed"

def test_upsert_dedupe_returns_existing_on_hash_collision(tmp_path):
    conn, nb = _ctx(tmp_path)
    first = create_source(conn, notebook_id=nb.id, kind="md", origin="a.md", content_hash="dup")
    dup_or_new, was_new = upsert_dedupe(
        conn,
        notebook_id=nb.id,
        kind="md",
        origin="a-copy.md",
        content_hash="dup",
    )
    assert not was_new
    assert dup_or_new.id == first.id

def test_get_missing_source(tmp_path):
    conn, nb = _ctx(tmp_path)
    with pytest.raises(AppError) as excinfo:
        get_source(conn, "xxx")
    assert excinfo.value.code == ErrorCode.STORAGE_NOT_FOUND

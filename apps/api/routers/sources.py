from __future__ import annotations

import shutil

import httpx
from fastapi import APIRouter, BackgroundTasks, File, Path, Request, UploadFile
from fastapi.responses import Response

from apps.api.routers.audio import _AUDIO_EXT_PRIORITY, _resolve_audio_path
from apps.api.schemas.source import Source, SourceRename, SourceUrlCreate
from apps.api.schemas.source_content import (
    DocumentContent,
    DocumentSection,
    RecordingContent,
    RecordingSegment,
    SpeakerRename,
)
from core.exceptions import AppError, ErrorCode
from core.ingestion.parsers import get_parser
from core.ingestion.hashing import sha256_bytes
from core.storage import notebooks_repo, sources_repo
from core.storage.chunks_repo import (
    delete_chunks_for_source,
    list_chunks_for_source,
    rename_speaker_in_source,
)

router = APIRouter(prefix="/api/notebooks", tags=["sources"])


_KIND_BY_EXT = {
    ".pdf": "pdf",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "txt",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
}

_EXT_BY_KIND = {
    "pdf": ".pdf",
    "markdown": ".md",
    "txt": ".txt",
    "docx": ".docx",
    "pptx": ".pptx",
    "xlsx": ".xlsx",
    "web": ".html",
}

# Document-kind sources store a flat original file (sources_dir/<id><ext>) and
# are re-parsed on demand. "recording" stores per-channel audio + chunks instead.
_DOCUMENT_KINDS = frozenset(_EXT_BY_KIND.keys())


def _kind_from_filename(name: str) -> str:
    name_lower = name.lower()
    for ext, kind in _KIND_BY_EXT.items():
        if name_lower.endswith(ext):
            return kind
    raise AppError(
        ErrorCode.INGESTION_UNSUPPORTED_KIND,
        f"unsupported file extension for {name}",
    )


def _has_recording_audio(rec, sources_dir) -> bool:
    if rec.kind != "recording":
        return False
    base = sources_dir / rec.id
    if not base.is_dir():
        return False
    return any(
        _resolve_audio_path(base, ch) is not None for ch in ("mic", "system")
    )


def _to_schema(rec, sources_dir) -> Source:
    return Source(
        id=rec.id,
        notebook_id=rec.notebook_id,
        kind=rec.kind,
        title=rec.title,
        origin=rec.origin,
        status=rec.status.value,
        error_msg=rec.error_msg,
        bytes=rec.bytes,
        page_count=rec.page_count,
        chunk_count=rec.chunk_count,
        has_audio=_has_recording_audio(rec, sources_dir),
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )


@router.post("/{notebook_id}/sources", status_code=202, response_model=Source)
async def upload_file(
    request: Request,
    background: BackgroundTasks,
    notebook_id: str = Path(...),
    file: UploadFile = File(...),
) -> Source:
    ctx = request.app.state.ctx
    notebooks_repo.get_notebook(ctx.conn, notebook_id)
    data = await file.read()
    kind = _kind_from_filename(file.filename or "")
    digest = sha256_bytes(data)
    rec, was_new = sources_repo.upsert_dedupe(
        ctx.conn,
        notebook_id=notebook_id,
        kind=kind,
        content_hash=digest,
        origin=file.filename,
        bytes_=len(data),
    )
    if was_new:
        ext = _EXT_BY_KIND.get(kind, ".bin")
        source_path = ctx.config.sources_dir / f"{rec.id}{ext}"
        source_path.write_bytes(data)
        background.add_task(ctx.pipeline.run, source_id=rec.id, kind=kind, data=data)
    return _to_schema(rec, ctx.config.sources_dir)


_CONTENT_TYPE_KIND: dict[str, str] = {
    "application/pdf": "pdf",
    "application/x-pdf": "pdf",
    "text/markdown": "markdown",
    "text/x-markdown": "markdown",
    "text/plain": "txt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}


def _detect_url_kind(*, url: str, content_type: str | None, data: bytes) -> str:
    """Pick the parser kind for a fetched URL by content-type, magic bytes, then path."""
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    if ct in _CONTENT_TYPE_KIND:
        return _CONTENT_TYPE_KIND[ct]
    if data.startswith(b"%PDF-"):
        return "pdf"
    if ct.startswith("text/html") or ct.startswith("application/xhtml"):
        return "web"
    url_lower = url.lower().split("?", 1)[0]
    for ext, k in _KIND_BY_EXT.items():
        if url_lower.endswith(ext):
            return k
    return "web"


@router.post("/{notebook_id}/sources/url", status_code=202, response_model=Source)
async def upload_url(
    request: Request,
    background: BackgroundTasks,
    notebook_id: str,
    body: SourceUrlCreate,
) -> Source:
    ctx = request.app.state.ctx
    notebooks_repo.get_notebook(ctx.conn, notebook_id)
    url = str(body.url)
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
            r = await c.get(url)
            r.raise_for_status()
    except httpx.HTTPError as exc:
        raise AppError(
            ErrorCode.INGESTION_FETCH_FAILED, "failed to fetch URL", detail=str(exc)
        ) from exc
    data = r.content
    kind = _detect_url_kind(
        url=url, content_type=r.headers.get("content-type"), data=data
    )
    digest = sha256_bytes(data)
    rec, was_new = sources_repo.upsert_dedupe(
        ctx.conn,
        notebook_id=notebook_id,
        kind=kind,
        content_hash=digest,
        origin=url,
        bytes_=len(data),
    )
    if was_new:
        ext = _EXT_BY_KIND.get(kind, ".bin")
        source_path = ctx.config.sources_dir / f"{rec.id}{ext}"
        source_path.write_bytes(data)
        background.add_task(ctx.pipeline.run, source_id=rec.id, kind=kind, data=data)
    return _to_schema(rec, ctx.config.sources_dir)


@router.get("/{notebook_id}/sources", response_model=list[Source])
async def list_sources(request: Request, notebook_id: str) -> list[Source]:
    ctx = request.app.state.ctx
    notebooks_repo.get_notebook(ctx.conn, notebook_id)
    return [_to_schema(r, ctx.config.sources_dir) for r in sources_repo.list_sources(ctx.conn, notebook_id=notebook_id)]


@router.delete("/{notebook_id}/sources/{source_id}", status_code=204)
async def delete_source(request: Request, notebook_id: str, source_id: str) -> Response:
    ctx = request.app.state.ctx
    src = sources_repo.get_source(ctx.conn, source_id)
    if src.notebook_id != notebook_id:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "source not in notebook")
    delete_chunks_for_source(ctx.conn, source_id)
    ctx.vector_store.delete_by_source(source_id)
    ctx.conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    ext = _EXT_BY_KIND.get(src.kind, ".bin")
    source_path = ctx.config.sources_dir / f"{src.id}{ext}"
    if source_path.exists():
        source_path.unlink()
    # Recording sources keep their audio under a per-source directory
    # (sources_dir/<id>/mic.m4a, system.wav, …), not a flat file, so the unlink
    # above never reaches them. Remove the whole directory if present.
    rec_dir = ctx.config.sources_dir / src.id
    if rec_dir.is_dir():
        shutil.rmtree(rec_dir, ignore_errors=True)
    return Response(status_code=204)


@router.patch("/{notebook_id}/sources/{source_id}", response_model=Source)
async def rename_source(
    request: Request,
    notebook_id: str,
    source_id: str,
    body: SourceRename,
) -> Source:
    ctx = request.app.state.ctx
    src = sources_repo.get_source(ctx.conn, source_id)
    if src.notebook_id != notebook_id:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "source not in notebook")
    title = body.title.strip()
    if not title:
        raise AppError(ErrorCode.INPUT_INVALID, "title must not be empty")
    updated = sources_repo.update_source_title(ctx.conn, source_id, title)
    return _to_schema(updated, ctx.config.sources_dir)


@router.patch("/{notebook_id}/sources/{source_id}/speaker")
async def rename_speaker(
    request: Request,
    notebook_id: str,
    source_id: str,
    body: SpeakerRename,
) -> dict:
    """Bulk-rename one speaker label across all chunks of a source (within-source).

    Updates both SQLite (source of truth) and the Qdrant payload (best-effort).
    """
    ctx = request.app.state.ctx
    to_label = body.to_label.strip()
    if not to_label:
        raise AppError(ErrorCode.INPUT_INVALID, "to_label must not be empty")
    src = sources_repo.get_source(ctx.conn, source_id)
    if src.notebook_id != notebook_id:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "source not in notebook")
    updated = rename_speaker_in_source(
        ctx.conn, source_id, body.from_label, to_label
    )
    # Qdrant payload is display-only; keep it in sync but never fail the request on it.
    ctx.vector_store.rename_speaker(source_id, body.from_label, to_label)
    return {"updated": updated}


@router.get("/{notebook_id}/sources/{source_id}/chunks/{chunk_id}")
async def get_chunk(
    request: Request, notebook_id: str, source_id: str, chunk_id: str
) -> dict:
    ctx = request.app.state.ctx
    rec = ctx.conn.execute(
        "SELECT * FROM chunks WHERE id = ? AND source_id = ?",
        (chunk_id, source_id),
    ).fetchone()
    if rec is None:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, f"chunk {chunk_id} not found")
    return {
        "id": rec["id"],
        "source_id": rec["source_id"],
        "page": rec["page"],
        "heading_path": rec["heading_path"],
        "text": rec["text"],
        "start_ms": rec["start_ms"],
        "end_ms": rec["end_ms"],
        "speaker": rec["speaker"],
    }


@router.get(
    "/{notebook_id}/sources/{source_id}/content",
    response_model=DocumentContent | RecordingContent,
)
async def get_source_content(
    request: Request, notebook_id: str, source_id: str
) -> DocumentContent | RecordingContent:
    """Return faithful full content for a source.

    Documents are re-parsed from their stored original bytes (cost is paid on
    each view; cache later if measured). Recordings return their generated
    transcript chunks ordered by ``ord``.
    """
    ctx = request.app.state.ctx
    src = sources_repo.get_source(ctx.conn, source_id)
    if src.notebook_id != notebook_id:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "source not in notebook")

    if src.kind == "recording":
        segments = [
            RecordingSegment(
                ord=c.ord,
                text=c.text,
                start_ms=c.start_ms,
                end_ms=c.end_ms,
                speaker=c.speaker,
            )
            for c in list_chunks_for_source(ctx.conn, source_id)
        ]
        return RecordingContent(segments=segments)

    if src.kind not in _DOCUMENT_KINDS:
        raise AppError(
            ErrorCode.INGESTION_UNSUPPORTED_KIND,
            f"no full-content view for kind={src.kind}",
        )

    ext = _EXT_BY_KIND.get(src.kind, ".bin")
    source_path = ctx.config.sources_dir / f"{src.id}{ext}"
    if not source_path.exists():
        raise AppError(
            ErrorCode.INPUT_INVALID,
            "original source data not found on disk",
            remediation="re-upload the file",
        )
    data = source_path.read_bytes()
    parser = get_parser(src.kind)
    doc = parser.parse_bytes(data, source_hint=src.origin)
    sections = [
        DocumentSection(
            heading_path=" > ".join(s.heading_path) if s.heading_path else None,
            page=s.page,
            text=s.text,
        )
        for s in doc.sections
    ]
    return DocumentContent(sections=sections)


@router.post("/{notebook_id}/sources/{source_id}/retry", response_model=Source)
async def retry_source(
    request: Request,
    background: BackgroundTasks,
    notebook_id: str,
    source_id: str,
) -> Source:
    ctx = request.app.state.ctx
    src = sources_repo.get_source(ctx.conn, source_id)
    if src.notebook_id != notebook_id:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "source not in notebook")
    ext = _EXT_BY_KIND.get(src.kind, ".bin")
    source_path = ctx.config.sources_dir / f"{src.id}{ext}"
    if not source_path.exists():
        raise AppError(
            ErrorCode.INPUT_INVALID,
            "original source data not found on disk",
            remediation="re-upload the file",
        )
    data = source_path.read_bytes()
    # clear prior chunks (vector + sqlite)
    delete_chunks_for_source(ctx.conn, source_id)
    ctx.vector_store.delete_by_source(source_id)
    # reset status
    sources_repo.update_source_status(
        ctx.conn, source_id,
        status=sources_repo.SourceStatus.PENDING,
        error_msg=None,
    )
    background.add_task(ctx.pipeline.run, source_id=src.id, kind=src.kind, data=data)
    return _to_schema(sources_repo.get_source(ctx.conn, source_id), ctx.config.sources_dir)

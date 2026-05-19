from __future__ import annotations

import httpx
from fastapi import APIRouter, BackgroundTasks, File, Path, Request, UploadFile, status
from fastapi.responses import Response

from apps.api.schemas.source import Source, SourceUrlCreate
from core.exceptions import AppError, ErrorCode
from core.ingestion.hashing import sha256_bytes
from core.ingestion.parsers import known_kinds
from core.storage import notebooks_repo, sources_repo
from core.storage.chunks_repo import delete_chunks_for_source


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


def _kind_from_filename(name: str) -> str:
    name_lower = name.lower()
    for ext, kind in _KIND_BY_EXT.items():
        if name_lower.endswith(ext):
            return kind
    raise AppError(
        ErrorCode.INGESTION_UNSUPPORTED_KIND,
        f"unsupported file extension for {name}",
    )


def _to_schema(rec) -> Source:
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
        background.add_task(ctx.pipeline.run, source_id=rec.id, kind=kind, data=data)
    return _to_schema(rec)


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
    digest = sha256_bytes(data)
    rec, was_new = sources_repo.upsert_dedupe(
        ctx.conn,
        notebook_id=notebook_id,
        kind="web",
        content_hash=digest,
        origin=url,
        bytes_=len(data),
    )
    if was_new:
        background.add_task(ctx.pipeline.run, source_id=rec.id, kind="web", data=data)
    return _to_schema(rec)


@router.get("/{notebook_id}/sources", response_model=list[Source])
async def list_sources(request: Request, notebook_id: str) -> list[Source]:
    ctx = request.app.state.ctx
    notebooks_repo.get_notebook(ctx.conn, notebook_id)
    return [_to_schema(r) for r in sources_repo.list_sources(ctx.conn, notebook_id=notebook_id)]


@router.delete("/{notebook_id}/sources/{source_id}", status_code=204)
async def delete_source(request: Request, notebook_id: str, source_id: str) -> Response:
    ctx = request.app.state.ctx
    src = sources_repo.get_source(ctx.conn, source_id)
    if src.notebook_id != notebook_id:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "source not in notebook")
    delete_chunks_for_source(ctx.conn, source_id)
    ctx.vector_store.delete_by_source(source_id)
    ctx.conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    return Response(status_code=204)


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
    # the actual bytes must be re-supplied or we read from sources_dir;
    # for MVP, retry is only valid for URL sources (re-fetch) or when we kept the file
    raise AppError(
        ErrorCode.INPUT_INVALID,
        "retry not yet supported via API in this sprint",
        remediation="re-upload the file",
    )

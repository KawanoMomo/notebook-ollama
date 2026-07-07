"""スライド PDF 配信(spec §5)。pdf.js が fetch するだけなので FileResponse で十分。"""
from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.responses import FileResponse

from core.exceptions import AppError, ErrorCode
from core.ingestion.pptx_to_pdf import slides_pdf_path
from core.storage import sources_repo

router = APIRouter(tags=["slides"])


@router.get("/api/notebooks/{notebook_id}/sources/{source_id}/slides")
async def get_source_slides(request: Request, notebook_id: str, source_id: str):
    ctx = request.app.state.ctx
    src = sources_repo.get_source(ctx.conn, source_id)
    if src.notebook_id != notebook_id:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "source not in notebook")
    path = slides_pdf_path(ctx.config.sources_dir, source_id, src.kind)
    if path is None or not path.exists():
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "slides not available")
    return FileResponse(
        path, media_type="application/pdf", headers={"Accept-Ranges": "bytes"}
    )

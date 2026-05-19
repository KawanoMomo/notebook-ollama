from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import Response

from apps.api.schemas.notebook import Notebook, NotebookCreate, NotebookUpdate
from core.storage import notebooks_repo, sources_repo


router = APIRouter(prefix="/api/notebooks", tags=["notebooks"])


def _to_schema(rec, source_count: int = 0) -> Notebook:
    return Notebook(
        id=rec.id,
        name=rec.name,
        description=rec.description,
        default_model=rec.default_model,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
        source_count=source_count,
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Notebook)
async def create(request: Request, body: NotebookCreate) -> Notebook:
    ctx = request.app.state.ctx
    rec = notebooks_repo.create_notebook(
        ctx.conn,
        name=body.name,
        description=body.description,
        default_model=body.default_model,
    )
    return _to_schema(rec)


@router.get("", response_model=list[Notebook])
async def list_(request: Request) -> list[Notebook]:
    ctx = request.app.state.ctx
    out: list[Notebook] = []
    for rec in notebooks_repo.list_notebooks(ctx.conn):
        srcs = sources_repo.list_sources(ctx.conn, notebook_id=rec.id)
        out.append(_to_schema(rec, source_count=len(srcs)))
    return out


@router.get("/{notebook_id}", response_model=Notebook)
async def get(request: Request, notebook_id: str) -> Notebook:
    ctx = request.app.state.ctx
    rec = notebooks_repo.get_notebook(ctx.conn, notebook_id)
    srcs = sources_repo.list_sources(ctx.conn, notebook_id=rec.id)
    return _to_schema(rec, source_count=len(srcs))


@router.patch("/{notebook_id}", response_model=Notebook)
async def update(request: Request, notebook_id: str, body: NotebookUpdate) -> Notebook:
    ctx = request.app.state.ctx
    rec = notebooks_repo.update_notebook(
        ctx.conn,
        notebook_id,
        name=body.name,
        description=body.description,
        default_model=body.default_model,
    )
    return _to_schema(rec)


@router.delete("/{notebook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(request: Request, notebook_id: str) -> Response:
    ctx = request.app.state.ctx
    notebooks_repo.delete_notebook(ctx.conn, notebook_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

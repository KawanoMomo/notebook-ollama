"""手動リンク API (親設定/解除/一覧)。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel
from starlette.responses import Response

from apps.api.schemas.source import SourceLink
from core.exceptions import AppError, ErrorCode
from core.storage import notebooks_repo, source_links_repo, sources_repo

router = APIRouter(prefix="/api/notebooks", tags=["links"])


class SetParentRequest(BaseModel):
    parent_source_id: str


@router.put("/{notebook_id}/sources/{source_id}/parent")
async def set_parent(
    request: Request,
    notebook_id: Annotated[str, Path()],
    source_id: Annotated[str, Path()],
    body: SetParentRequest,
) -> SourceLink:
    """ソースの親を設定する(relation は 'manual' 固定)。

    ソースの存在・同一ノートブック所属・自己/循環リンク・不正な relation の
    検証はすべて repo の set_parent が行い、AppError を raise する。
    main.py の exception_handler が 400/404 に写像する。
    """
    ctx = request.app.state.ctx
    link = source_links_repo.set_parent(
        ctx.conn,
        notebook_id=notebook_id,
        parent_source_id=body.parent_source_id,
        child_source_id=source_id,
        relation="manual",
    )
    return SourceLink(
        id=link.id,
        notebook_id=link.notebook_id,
        parent_source_id=link.parent_source_id,
        child_source_id=link.child_source_id,
        relation=link.relation,
        meta=link.meta,
        created_at=link.created_at,
    )


@router.delete("/{notebook_id}/sources/{source_id}/parent", status_code=204)
async def remove_parent(
    request: Request,
    notebook_id: Annotated[str, Path()],
    source_id: Annotated[str, Path()],
):
    """ソースの親を削除する。リンクが無い場合も 204 を返す(冪等性)。

    repo の remove_parent は NB 検証を持たないため、ここで source の
    NB 所属を検証する(sources.py の delete_source と同パターン)。
    """
    ctx = request.app.state.ctx
    src = sources_repo.get_source(ctx.conn, source_id)
    if src.notebook_id != notebook_id:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "source not found in notebook")
    source_links_repo.remove_parent(ctx.conn, source_id)
    return Response(status_code=204)


@router.get("/{notebook_id}/source-links")
async def list_links(
    request: Request,
    notebook_id: Annotated[str, Path()],
) -> list[SourceLink]:
    """ノートブック内のすべてのソース親子リンクを一覧する(FE のツリー表示用)。

    存在しない NB は 404(sources.py の list_sources と同パターン)。
    """
    ctx = request.app.state.ctx
    notebooks_repo.get_notebook(ctx.conn, notebook_id)
    links = source_links_repo.list_links_for_notebook(ctx.conn, notebook_id)
    return [
        SourceLink(
            id=link.id,
            notebook_id=link.notebook_id,
            parent_source_id=link.parent_source_id,
            child_source_id=link.child_source_id,
            relation=link.relation,
            meta=link.meta,
            created_at=link.created_at,
        )
        for link in links
    ]

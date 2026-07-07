"""手動リンク API (親設定/解除/一覧)。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel
from starlette.responses import Response

from apps.api.schemas.source import SourceLink
from core.storage import source_links_repo, sources_repo

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

    両ソースが同一ノートブックに属すること、自己/循環リンク、
    不正な relation を拒否する。これらは repo で AppError を raise し、
    main.py の exception_handler が自動で 400 に写像する。
    """
    ctx = request.app.state.ctx

    # ソースの存在を確認(cross-notebook 検証は repo 内で行われる)
    sources_repo.get_source(ctx.conn, source_id)
    sources_repo.get_source(ctx.conn, body.parent_source_id)

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
    """ソースの親を削除する。リンクが無い場合も 204 を返す(冪等性)。"""
    ctx = request.app.state.ctx
    source_links_repo.remove_parent(ctx.conn, source_id)
    return Response(status_code=204)


@router.get("/{notebook_id}/source-links")
async def list_links(
    request: Request,
    notebook_id: Annotated[str, Path()],
) -> list[SourceLink]:
    """ノートブック内のすべてのソース親子リンクを一覧する(FE のツリー表示用)。"""
    ctx = request.app.state.ctx
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

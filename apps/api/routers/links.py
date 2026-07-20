"""手動リンク API (親設定/解除/一覧)。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel
from starlette.responses import Response

from apps.api.schemas.source import SlideUtteranceItem, SlideUtterancePage, SourceLink
from core.exceptions import AppError, ErrorCode
from core.storage import notebooks_repo, source_links_repo, sources_repo
from core.storage.chunks_repo import list_chunks_for_source

router = APIRouter(prefix="/api/notebooks", tags=["links"])

_SLIDE_KINDS = ("pdf", "pptx")


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


@router.get("/{notebook_id}/sources/{source_id}/slide-utterances")
async def slide_utterances(
    request: Request,
    notebook_id: Annotated[str, Path()],
    source_id: Annotated[str, Path()],
) -> list[SlideUtterancePage]:
    """発表資料(source_id)の各ページで発言された録音チャンクの逆引き(spec §7)。

    source_id はスライド資料(kind∈{pdf,pptx})のみ許可、それ以外は 400。
    NB 不一致/未知 source_id は 404(sources.py の get_source_content と同パターン)。
    source_links で子(全 relation)を辿り、kind=recording の子のみ対象に
    list_chunks_for_source から page が非 NULL のチャンクを集めてページ昇順に
    グループ化する。手動リンクは任意ソースを子にできるため、PDF 等の非録音子の
    文書チャンク(page 非 null・start_ms/speaker は None)を偽の「発言」として
    返さない。items は (child_source_id, start_ms) 順。子ゼロ/該当チャンク
    ゼロなら [] を返す。
    """
    ctx = request.app.state.ctx
    src = sources_repo.get_source(ctx.conn, source_id)
    if src.notebook_id != notebook_id:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "source not in notebook")
    if src.kind not in _SLIDE_KINDS:
        raise AppError(
            ErrorCode.INPUT_INVALID,
            f"source kind={src.kind} is not a slide deck (pdf/pptx)",
        )

    by_page: dict[int, list[SlideUtteranceItem]] = {}
    for link in source_links_repo.list_child_links(ctx.conn, source_id):
        child = sources_repo.get_source(ctx.conn, link.child_source_id)
        if child.kind != "recording":
            continue
        for c in list_chunks_for_source(ctx.conn, link.child_source_id):
            if c.page is None:
                continue
            by_page.setdefault(c.page, []).append(
                SlideUtteranceItem(
                    child_source_id=c.source_id,
                    child_title=child.title,
                    chunk_id=c.id,
                    start_ms=c.start_ms,
                    end_ms=c.end_ms,
                    speaker=c.speaker,
                    text=c.text,
                )
            )
    return [
        SlideUtterancePage(
            page=page,
            items=sorted(
                by_page[page],
                key=lambda it: (
                    it.child_source_id,
                    it.start_ms if it.start_ms is not None else 0,
                ),
            ),
        )
        for page in sorted(by_page)
    ]

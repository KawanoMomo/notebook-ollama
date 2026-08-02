from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import Response

from apps.api.schemas.notebook import Notebook, NotebookCreate, NotebookUpdate
from core.logging import get_logger
from core.storage import notebooks_repo, sources_repo

router = APIRouter(prefix="/api/notebooks", tags=["notebooks"])

_log = get_logger("apps.api.routers.notebooks")


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
    fields = body.model_dump(exclude_unset=True)
    clear_default_model = "default_model" in fields and fields["default_model"] is None
    rec = notebooks_repo.update_notebook(
        ctx.conn,
        notebook_id,
        name=body.name,
        description=body.description,
        default_model=body.default_model,
        clear_default_model=clear_default_model,
    )
    return _to_schema(rec)


@router.delete("/{notebook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(request: Request, notebook_id: str) -> Response:
    ctx = request.app.state.ctx
    # 視覚索引はノートブックの外 (Qdrant の別コレクション + visual_index_* テーブル)
    # にあり、notebooks の DELETE では消えない。先に落としておかないと、
    # ノートブックを消してもベクトルと索引メタが孤児として残り続ける。
    # 索引が無い/視覚extra未導入なら no-op なので無条件に呼んでよい。
    _delete_visual_index(ctx, notebook_id)
    notebooks_repo.delete_notebook(ctx.conn, notebook_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _delete_visual_index(ctx, notebook_id: str) -> None:
    """ノートブックに紐づく視覚索引 (全単位) を落とす。

    ノートブック削除は「消せなかったので 500」より「本体は消えた」を優先する
    (残骸は再構築で上書きされる)。掃除の失敗は握ってログに出す。
    """
    from core.storage.visual_index_repo import delete_meta

    stores = getattr(ctx, "visual_stores", None) or {}
    for unit, store in stores.items():
        try:
            store.delete_by_notebook(notebook_id)
        except Exception:
            _log.warning(
                "notebook_delete_visual_vectors_failed",
                notebook_id=notebook_id, unit=unit, exc_info=True,
            )
    try:
        delete_meta(ctx.conn, notebook_id)   # unit=None = 全単位
    except Exception:
        _log.warning(
            "notebook_delete_visual_meta_failed", notebook_id=notebook_id, exc_info=True
        )

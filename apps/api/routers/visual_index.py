"""視覚インデックス構築/状態/削除 API (Stage 3, spec §8)。"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from apps.api.routers.features import require_feature
from core.exceptions import AppError, ErrorCode
from core.logging import get_logger
from core.storage.sources_repo import SourceStatus, list_sources
from core.storage.visual_index_repo import delete_meta, get_meta, list_indexed_source_ids
from core.visual.encoder import visual_extra_available
from core.visual.index_builder import (
    BuilderDeps,
    VisualIndexBuilder,
    is_building,
    mark_building,
    unmark_building,
)

log = get_logger("api.visual_index")

router = APIRouter(
    prefix="/api/notebooks",
    tags=["visual-index"],
    dependencies=[Depends(require_feature("table-figure-rag"))],
)


def _require_extra() -> None:
    if not visual_extra_available():
        raise AppError(
            ErrorCode.INGESTION_DEP_MISSING,
            "視覚埋め込みの依存が未導入です",
            remediation="`uv sync --extra visual` を実行してください。",
        )


def _pending_sources(ctx, notebook_id: str) -> int:
    indexed = list_indexed_source_ids(ctx.conn, notebook_id)
    return sum(
        1 for s in list_sources(ctx.conn, notebook_id=notebook_id)
        if s.kind == "pdf" and s.status == SourceStatus.READY and s.id not in indexed
    )


@router.get("/{notebook_id}/visual-index")
async def get_visual_index_status(request: Request, notebook_id: str) -> dict:
    ctx = request.app.state.ctx
    meta = get_meta(ctx.conn, notebook_id)
    return {
        "built": meta is not None,
        "embedding_model": meta.embedding_model if meta else None,
        "built_at": meta.built_at if meta else None,
        "indexed_sources": len(list_indexed_source_ids(ctx.conn, notebook_id)),
        "pending_sources": _pending_sources(ctx, notebook_id),
        "building": is_building(notebook_id),
        "extra_available": visual_extra_available(),
    }


async def _run_build(ctx, notebook_id: str) -> None:
    async def progress(done: int, total: int) -> None:
        await ctx.sse.publish(
            f"notebook:{notebook_id}",
            {"type": "visual_index_progress", "done": done, "total": total},
        )

    try:
        builder = VisualIndexBuilder(deps=BuilderDeps(
            conn=ctx.conn,
            visual_store=ctx.visual_store,
            encoder=ctx.visual_encoder,
            sources_dir=ctx.config.sources_dir,
            assets_dir=ctx.config.assets_dir,
            embedding_model_name=ctx.config.visual.embedding_model,
            render_dpi=ctx.config.visual.render_dpi,
            progress=progress,
            page_cooldown_seconds=ctx.config.visual.build_cooldown_seconds,
        ))
        result = await builder.build(notebook_id)
        await ctx.sse.publish(
            f"notebook:{notebook_id}",
            {
                "type": "visual_index_complete",
                "indexed_pages": result.indexed_pages,
                "skipped_pages": result.skipped_pages,
            },
        )
    except Exception:
        log.warning("visual_index_build_failed", notebook_id=notebook_id, exc_info=True)
        await ctx.sse.publish(
            f"notebook:{notebook_id}", {"type": "visual_index_error"}
        )
    finally:
        unmark_building(notebook_id)
        # ビルド後はエンコーダをアイドル解放候補にする(即時解放はしない —
        # 直後のクエリで再ロードさせないため。定期チェックは encoder 側)。
        # VisualEncoder Protocol には maybe_unload_if_idle が無い(テスト用
        # Fake実装は持たない)ため、実装している具象型(TransformersVisualEncoder)
        # のときだけ呼ぶ。
        unload = getattr(ctx.visual_encoder, "maybe_unload_if_idle", None)
        if callable(unload):
            unload()


@router.post("/{notebook_id}/visual-index", status_code=202)
async def build_visual_index(
    request: Request, background: BackgroundTasks, notebook_id: str
) -> dict:
    ctx = request.app.state.ctx
    _require_extra()
    if ctx.visual_encoder is None:
        raise AppError(
            ErrorCode.INGESTION_DEP_MISSING,
            "視覚エンコーダが初期化されていません",
            remediation="`uv sync --extra visual` 後にサーバーを再起動してください。",
        )
    if is_building(notebook_id):
        return {"status": "already_building"}
    meta = get_meta(ctx.conn, notebook_id)
    if meta is not None and meta.embedding_model != ctx.config.visual.embedding_model:
        # モデル不一致 → 全再構築(spec §8)。既存索引を落としてから積み直す
        ctx.visual_store.delete_by_notebook(notebook_id)
        delete_meta(ctx.conn, notebook_id)
    mark_building(notebook_id)
    background.add_task(_run_build, ctx, notebook_id)
    return {"status": "accepted"}


@router.delete("/{notebook_id}/visual-index", status_code=204)
async def delete_visual_index(request: Request, notebook_id: str) -> None:
    ctx = request.app.state.ctx
    ctx.visual_store.delete_by_notebook(notebook_id)
    delete_meta(ctx.conn, notebook_id)
    # ページPNGは残す(spec §8: 再構築時のレンダリング省略ではなく、
    # 生成時のVLM投入がヒット済み索引に依存しないようにするため)

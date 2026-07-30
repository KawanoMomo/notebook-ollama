"""視覚インデックスの構築 / 状態 / 削除 API (Stage 3 → Stage 4 で単位対応)。

unit クエリパラメータで "page"(1ページ1ベクトル)と "tile"(PixelRAG式)を
選ぶ。両者は別コレクション・別メタ行なので独立に構築・削除できる。
GET は Modal が2行を1リクエストで描けるよう両単位をまとめて返す。
"""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request

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

UNITS = ("page", "tile")

# FastAPI が 422 を返すので、不正な unit のハンドリングはここで完結する
UnitParam = Annotated[Literal["page", "tile"], Query()]


def _require_extra() -> None:
    if not visual_extra_available():
        raise AppError(
            ErrorCode.INGESTION_DEP_MISSING,
            "視覚埋め込みの依存が未導入です",
            remediation="`uv sync --extra visual` を実行してください。",
        )


def _pending_sources(ctx, notebook_id: str, unit: str) -> int:
    indexed = list_indexed_source_ids(ctx.conn, notebook_id, unit)
    return sum(
        1
        for s in list_sources(ctx.conn, notebook_id=notebook_id)
        if s.kind == "pdf" and s.status == SourceStatus.READY and s.id not in indexed
    )


def _unit_status(ctx, notebook_id: str, unit: str) -> dict:
    meta = get_meta(ctx.conn, notebook_id, unit)
    return {
        "built": meta is not None,
        "embedding_model": meta.embedding_model if meta else None,
        "built_at": meta.built_at if meta else None,
        "indexed_sources": len(list_indexed_source_ids(ctx.conn, notebook_id, unit)),
        "pending_sources": _pending_sources(ctx, notebook_id, unit),
        "building": is_building(notebook_id, unit),
    }


def _store(ctx, unit: str):
    """単位に対応する VisualUnitStore。dependencies.build_context が両方作る。"""
    return ctx.visual_stores[unit]


async def _run_build(ctx, notebook_id: str, unit: str) -> None:
    async def progress(done: int, total: int) -> None:
        await ctx.sse.publish(
            f"notebook:{notebook_id}",
            {"type": "visual_index_progress", "unit": unit, "done": done, "total": total},
        )

    cfg = ctx.config
    try:
        builder = VisualIndexBuilder(
            deps=BuilderDeps(
                conn=ctx.conn,
                visual_store=_store(ctx, unit),
                encoder=ctx.visual_encoder,
                sources_dir=cfg.sources_dir,
                assets_dir=cfg.assets_dir,
                embedding_model_name=cfg.visual.embedding_model,
                render_dpi=cfg.visual.render_dpi,
                progress=progress,
                page_cooldown_seconds=cfg.visual.build_cooldown_seconds,
                unit=unit,
                tile_rows=cfg.visual.tile_rows,
                tile_cols=cfg.visual.tile_cols,
                tile_overlap=cfg.visual.tile_overlap,
            )
        )
        result = await builder.build(notebook_id)
        # 対象があったのに1件も索引できなかった構築を「完了」と通知しない。
        # ビルダは単位ごとの失敗もレンダリング失敗も握り潰して例外を投げない
        # 設計(部分成功)なので、例外の有無や skipped_pages だけで判定すると
        # 「1件も索引できていないのに成功トースト」になる。レンダリングが
        # 全ソースで失敗した場合は skipped_pages すら増えない。
        failed_entirely = result.target_sources > 0 and result.indexed_pages == 0
        await ctx.sse.publish(
            f"notebook:{notebook_id}",
            {
                "type": "visual_index_error" if failed_entirely else "visual_index_complete",
                "unit": unit,
                "indexed_pages": result.indexed_pages,
                "skipped_pages": result.skipped_pages,
                "indexed_tiles": result.indexed_tiles,
            },
        )
    except Exception:
        log.warning("visual_index_build_failed", notebook_id=notebook_id, unit=unit, exc_info=True)
        await ctx.sse.publish(
            f"notebook:{notebook_id}", {"type": "visual_index_error", "unit": unit}
        )
    finally:
        unmark_building(notebook_id, unit)
        # ビルド後はエンコーダをアイドル解放候補にする(即時解放はしない —
        # 直後のクエリで再ロードさせないため。定期チェックは encoder 側)。
        # VisualEncoder Protocol には maybe_unload_if_idle が無い(テスト用
        # Fake実装は持たない)ため、実装している具象型(TransformersVisualEncoder)
        # のときだけ呼ぶ。
        maybe_unload = getattr(ctx.visual_encoder, "maybe_unload_if_idle", None)
        if callable(maybe_unload):
            maybe_unload()


@router.get("/{notebook_id}/visual-index")
async def get_visual_index_status(request: Request, notebook_id: str) -> dict:
    ctx = request.app.state.ctx
    return {
        "extra_available": visual_extra_available(),
        "index_unit": ctx.config.visual.index_unit,
        "search_strategy": ctx.config.visual.search_strategy,
        "units": {u: _unit_status(ctx, notebook_id, u) for u in UNITS},
    }


@router.post("/{notebook_id}/visual-index", status_code=202)
async def build_visual_index(
    request: Request,
    background: BackgroundTasks,
    notebook_id: str,
    unit: UnitParam = "page",
) -> dict:
    ctx = request.app.state.ctx
    _require_extra()
    if ctx.visual_encoder is None:
        raise AppError(
            ErrorCode.INGESTION_DEP_MISSING,
            "視覚エンコーダが初期化されていません",
            remediation="`uv sync --extra visual` 後にサーバーを再起動してください。",
        )
    if is_building(notebook_id, unit):
        return {"status": "already_building", "unit": unit}

    meta = get_meta(ctx.conn, notebook_id, unit)
    if meta is not None and meta.embedding_model != ctx.config.visual.embedding_model:
        # モデルが変わったら、その単位の索引だけ落として全再構築する
        _store(ctx, unit).delete_by_notebook(notebook_id)
        delete_meta(ctx.conn, notebook_id, unit)

    mark_building(notebook_id, unit)
    background.add_task(_run_build, ctx, notebook_id, unit)
    return {"status": "accepted", "unit": unit}


@router.delete("/{notebook_id}/visual-index", status_code=204)
async def delete_visual_index(
    request: Request, notebook_id: str, unit: UnitParam = "page"
) -> None:
    ctx = request.app.state.ctx
    # ページPNG / タイルPNG は意図的に残す(再構築時のレンダリング省略には
    # 使わないが、引用クリックの表示に使われる可能性があるため)。
    _store(ctx, unit).delete_by_notebook(notebook_id)
    delete_meta(ctx.conn, notebook_id, unit)

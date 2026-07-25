from __future__ import annotations

import shutil
from typing import Annotated

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, Path, Request, UploadFile
from fastapi.responses import Response
from starlette.responses import FileResponse

from apps.api.routers.audio import _resolve_audio_path
from apps.api.routers.features import require_feature
from apps.api.schemas.source import Source, SourceRename, SourceUrlCreate
from apps.api.schemas.source_content import (
    DocumentContent,
    DocumentSection,
    RecordingContent,
    RecordingSegment,
    SpeakerRename,
)
from core.exceptions import AppError, ErrorCode
from core.ingestion.hashing import sha256_bytes
from core.ingestion.parsers import get_parser
from core.ingestion.pptx_to_pdf import slides_pdf_path
from core.logging import get_logger
from core.storage import notebooks_repo, sources_repo
from core.storage.assets_repo import delete_assets_for_source, list_assets_for_source
from core.storage.chunks_repo import (
    delete_chunks_for_source,
    list_chunks_for_source,
    rename_speaker_in_source,
)
from core.storage.visual_index_repo import delete_indexed_source

router = APIRouter(prefix="/api/notebooks", tags=["sources"])

log = get_logger("api.sources")


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


def _has_slides(rec, sources_dir) -> bool:
    """発表モード用 PDF が既に存在するか(pdf 原本 or pptx の COM 併産物)。"""
    path = slides_pdf_path(sources_dir, rec.id, rec.kind)
    return path is not None and path.exists()


async def _convert_slides_best_effort(ctx, source_id: str, pptx_path) -> None:
    """PPTX 取込時の PDF 併産(best-effort、spec §8: 失敗しても取込は継続)。"""
    import asyncio

    from core.ingestion.pptx_to_pdf import convert_pptx_to_pdf, is_powerpoint_available

    if not is_powerpoint_available():
        return
    dst = slides_pdf_path(ctx.config.sources_dir, source_id, "pptx")
    try:
        await asyncio.wait_for(
            asyncio.to_thread(convert_pptx_to_pdf, pptx_path, dst), timeout=120.0
        )
    except Exception as exc:
        # COM は対話ユーザーセッション前提で環境依存の失敗をしうる。取込自体は
        # 継続させたいので、ここで完全に握りつぶし警告ログだけ残す(spec §8)。
        log.warning("pptx_slides_conversion_failed", source_id=source_id, error=str(exc))


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
        has_slides=_has_slides(rec, sources_dir),
        summary=rec.summary,
        summary_status=(
            rec.summary_status.value if rec.summary_status is not None else None
        ),
        adr_draft=rec.adr_draft,
        adr_status=(
            rec.adr_status.value if rec.adr_status is not None else None
        ),
        adr_template=rec.adr_template,
        adr_confidence=rec.adr_confidence,
        adr_generated_at=rec.adr_generated_at,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )


@router.post("/{notebook_id}/sources", status_code=202, response_model=Source)
async def upload_file(
    request: Request,
    background: BackgroundTasks,
    notebook_id: Annotated[str, Path(...)],
    file: Annotated[UploadFile, File(...)],
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
        if kind == "pptx":
            background.add_task(_convert_slides_best_effort, ctx, rec.id, source_path)
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
        if kind == "pptx":
            background.add_task(_convert_slides_best_effort, ctx, rec.id, source_path)
    return _to_schema(rec, ctx.config.sources_dir)


@router.get("/{notebook_id}/sources", response_model=list[Source])
async def list_sources(request: Request, notebook_id: str) -> list[Source]:
    ctx = request.app.state.ctx
    notebooks_repo.get_notebook(ctx.conn, notebook_id)
    return [
        _to_schema(r, ctx.config.sources_dir)
        for r in sources_repo.list_sources(ctx.conn, notebook_id=notebook_id)
    ]


@router.delete("/{notebook_id}/sources/{source_id}", status_code=204)
async def delete_source(request: Request, notebook_id: str, source_id: str) -> Response:
    ctx = request.app.state.ctx
    src = sources_repo.get_source(ctx.conn, source_id)
    if src.notebook_id != notebook_id:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "source not in notebook")
    delete_chunks_for_source(ctx.conn, source_id)
    ctx.vector_store.delete_by_source(source_id)
    ctx.visual_store.delete_by_source(source_id)
    delete_indexed_source(ctx.conn, source_id)
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
    # mic("あなた")は録音のチャンネル identity を兼ねる固定ラベル。リネームすると
    # フロントの mic/system 判定(色・シーク・音声ファイル選択)が壊れるため禁止する。
    # name_inference も "あなた" を自動改名から除外している(recording_pipeline._MIC_SPEAKER)。
    _MIC_LABEL = "あなた"
    if body.from_label == _MIC_LABEL or to_label == _MIC_LABEL:
        raise AppError(
            ErrorCode.INPUT_INVALID,
            "話者「あなた」(自分/マイク)はリネームできません",
        )
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
    if src.kind == "pdf":
        extract = ctx.features.is_enabled("table-figure-rag")
        try:
            doc = await parser.parse_bytes(data, source_hint=src.origin, extract_assets=extract)
        except AppError as exc:
            if exc.code != ErrorCode.INGESTION_PARSE_FAILED:
                raise
            # スキャンPDF(テキストレイヤー無し)。取込時にOCR済みの本文チャンクを
            # そのまま返す。閲覧のたびに全ページを再OCRしない — VLM呼び出しは
            # 1ページ数十秒かかり、グローバルchatロックも占有するため。またこの
            # フォールバックはベータOFFでも機能する(取込済みデータの閲覧は
            # spec の「データ自体は保持」の範囲で、OCR経路の再実行ではない)。
            text_chunks = [
                c for c in list_chunks_for_source(ctx.conn, source_id) if c.kind == "text"
            ]
            if not text_chunks:
                raise
            return DocumentContent(
                sections=[
                    DocumentSection(heading_path=c.heading_path, page=c.page, text=c.text)
                    for c in text_chunks
                ]
            )
    else:
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


@router.post(
    "/{notebook_id}/sources/{source_id}/summarize",
    status_code=202,
    response_model=Source,
)
async def summarize_source(
    request: Request,
    background: BackgroundTasks,
    notebook_id: str,
    source_id: str,
) -> Source:
    """summary_status を generating にリセットして SummaryJob を再起動する。

    要約が ready/error/未生成 のいずれの状態からでも呼べる(手動再生成用)。
    アプリ層に summary_runner が無い構成では status だけ反映して終了する。
    """
    ctx = request.app.state.ctx
    src = sources_repo.get_source(ctx.conn, source_id)
    if src.notebook_id != notebook_id:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "source not in notebook")
    # チャンク 0 件では SummaryJob が確実に失敗する。generating に遷移させる前に
    # 拒否し、ユーザーへは変換(再試行)を促す。
    if (src.chunk_count or 0) == 0:
        raise AppError(
            ErrorCode.INPUT_INVALID,
            "source has no chunks to summarize",
            remediation="先に変換(取込)を完了してください。録音は「再試行」で変換を再実行できます。",
        )
    sources_repo.update_source_summary_status(
        ctx.conn,
        source_id,
        status=sources_repo.SummaryStatus.GENERATING,
    )
    summary_runner = getattr(ctx, "summary_runner", None)
    if summary_runner is not None:
        background.add_task(summary_runner, source_id)
    return _to_schema(sources_repo.get_source(ctx.conn, source_id), ctx.config.sources_dir)


@router.post(
    "/{notebook_id}/sources/{source_id}/summarize/cancel",
    status_code=200,
    response_model=Source,
)
async def cancel_summarize(
    request: Request,
    notebook_id: str,
    source_id: str,
) -> Source:
    """実行中の要約ジョブを中断し、summary_status を未生成(None)へ戻す。

    実行タスクが見つからなくても summary_status が generating なら None に
    リセットする(サーバ再起動等で残留したスピナー状態の救済)。
    generating でなければ何もしない(冪等)。
    """
    ctx = request.app.state.ctx
    src = sources_repo.get_source(ctx.conn, source_id)
    if src.notebook_id != notebook_id:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "source not in notebook")

    registry = getattr(ctx, "summary_tasks", None)
    cancelled = registry.cancel(source_id) if registry is not None else False

    if cancelled or src.summary_status == sources_repo.SummaryStatus.GENERATING:
        src = sources_repo.update_source_summary_status(
            ctx.conn, source_id, status=None
        )
        # FE がリロードなしでスピナーを畳めるよう、明示 null を配信する
        await ctx.sse.publish(
            f"notebook:{src.notebook_id}",
            {
                "source_id": source_id,
                "status": src.status.value,
                "summary_status": None,
            },
        )
        log.info(
            "summary_cancelled",
            source_id=source_id,
            task_cancelled=cancelled,
        )
    return _to_schema(src, ctx.config.sources_dir)


@router.post(
    "/{notebook_id}/sources/{source_id}/adr",
    status_code=202,
    response_model=Source,
)
async def generate_adr(
    request: Request,
    background: BackgroundTasks,
    notebook_id: str,
    source_id: str,
) -> Source:
    """ADR 抽出ジョブを起動する。

    Decision Gate が yes なら Markdown ADR を生成、no なら skipped。
    既に generating でも上書き起動(MVP)。adr_runner が無い構成では status
    だけ generating に反映して終了する。
    """
    ctx = request.app.state.ctx
    src = sources_repo.get_source(ctx.conn, source_id)
    if src.notebook_id != notebook_id:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "source not in notebook")
    sources_repo.update_source_adr_status(
        ctx.conn,
        source_id,
        status=sources_repo.AdrStatus.GENERATING,
    )
    adr_runner = getattr(ctx, "adr_runner", None)
    if adr_runner is not None:
        background.add_task(adr_runner, source_id)
    return _to_schema(
        sources_repo.get_source(ctx.conn, source_id), ctx.config.sources_dir
    )


@router.delete(
    "/{notebook_id}/sources/{source_id}/adr",
    status_code=204,
)
async def delete_adr(
    request: Request, notebook_id: str, source_id: str
) -> Response:
    """adr_* 列を全て NULL に戻す。"""
    ctx = request.app.state.ctx
    src = sources_repo.get_source(ctx.conn, source_id)
    if src.notebook_id != notebook_id:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "source not in notebook")
    sources_repo.clear_source_adr(ctx.conn, source_id)
    return Response(status_code=204)


def _clear_source_derived_data(ctx, source_id: str) -> None:
    """チャンク・ベクタ・アセット(sqlite行 + PNGディレクトリ)を消す。

    retry / reingest の共通処理。sources テーブルの行と原本ファイルは消さない。
    """
    delete_chunks_for_source(ctx.conn, source_id)
    ctx.vector_store.delete_by_source(source_id)
    delete_assets_for_source(ctx.conn, source_id)
    shutil.rmtree(ctx.config.assets_dir / source_id, ignore_errors=True)
    ctx.visual_store.delete_by_source(source_id)
    delete_indexed_source(ctx.conn, source_id)


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
    _clear_source_derived_data(ctx, source_id)
    # reset status
    sources_repo.update_source_status(
        ctx.conn, source_id,
        status=sources_repo.SourceStatus.PENDING,
        error_msg=None,
    )
    background.add_task(ctx.pipeline.run, source_id=src.id, kind=src.kind, data=data)
    return _to_schema(sources_repo.get_source(ctx.conn, source_id), ctx.config.sources_dir)


@router.post(
    "/{notebook_id}/sources/{source_id}/reingest",
    status_code=202,
    dependencies=[Depends(require_feature("table-figure-rag"))],
)
async def reingest_source(
    request: Request, background: BackgroundTasks, notebook_id: str, source_id: str
) -> dict:
    """ベータ機能(表/図アセット抽出)を後から有効化した既存ソースを再取込する。"""
    ctx = request.app.state.ctx
    src = sources_repo.get_source(ctx.conn, source_id)
    if src.notebook_id != notebook_id:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "source not in notebook")
    if src.status not in (sources_repo.SourceStatus.READY, sources_repo.SourceStatus.ERROR):
        raise AppError(ErrorCode.STORAGE_CONFLICT, "取込処理中は再取込できません")
    ext = _EXT_BY_KIND.get(src.kind, ".bin")
    source_path = ctx.config.sources_dir / f"{source_id}{ext}"
    if not source_path.exists():
        raise AppError(
            ErrorCode.INPUT_INVALID,
            "原本ファイルがありません",
            remediation="ファイルを再アップロードしてください",
        )
    data = source_path.read_bytes()
    _clear_source_derived_data(ctx, source_id)
    sources_repo.update_source_status(
        ctx.conn, source_id, status=sources_repo.SourceStatus.PENDING, error_msg=None,
    )
    background.add_task(ctx.pipeline.run, source_id=source_id, kind=src.kind, data=data)
    return {"status": "accepted"}


@router.get(
    "/{notebook_id}/sources/{source_id}/assets",
    dependencies=[Depends(require_feature("table-figure-rag"))],
)
async def list_source_assets(request: Request, notebook_id: str, source_id: str) -> dict:
    ctx = request.app.state.ctx
    src = sources_repo.get_source(ctx.conn, source_id)
    if src.notebook_id != notebook_id:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "source not in notebook")
    rows = list_assets_for_source(ctx.conn, source_id)
    return {"assets": [vars(a) for a in rows]}


@router.post(
    "/{notebook_id}/sources/{source_id}/describe-figures",
    status_code=202,
    dependencies=[Depends(require_feature("table-figure-rag"))],
)
async def describe_figures(
    request: Request, background: BackgroundTasks, notebook_id: str, source_id: str
) -> dict:
    """未解析の図アセットをVLMで説明する(手動「図を解析」)。"""
    ctx = request.app.state.ctx
    src = sources_repo.get_source(ctx.conn, source_id)
    if src.notebook_id != notebook_id:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "source not in notebook")
    background.add_task(ctx.pipeline.describe_existing_figures, source_id=source_id)
    return {"status": "accepted"}


@router.get(
    "/{notebook_id}/sources/{source_id}/assets/{asset_id}",
    dependencies=[Depends(require_feature("table-figure-rag"))],
)
async def get_asset_image(
    request: Request, notebook_id: str, source_id: str, asset_id: str
) -> Response:
    ctx = request.app.state.ctx
    src = sources_repo.get_source(ctx.conn, source_id)
    if src.notebook_id != notebook_id:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "source not in notebook")
    assets = [a for a in list_assets_for_source(ctx.conn, source_id) if a.id == asset_id]
    if not assets or not assets[0].image_path:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "asset not found")
    path = ctx.config.assets_dir / assets[0].image_path
    if not path.exists():
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "asset image not found on disk")
    return FileResponse(path, media_type="image/png")

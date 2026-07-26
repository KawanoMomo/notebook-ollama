from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from core.exceptions import AppError, ErrorCode
from core.ids import new_id
from core.ingestion.chunker import ChunkOutput, chunk_document
from core.ingestion.parsers import get_parser
from core.ingestion.types import ParsedDocument, ParsedSection
from core.logging import get_logger
from core.storage.assets_repo import AssetRecord, insert_assets
from core.storage.chunks_repo import ChunkRecord, insert_chunks, list_chunks_for_source
from core.storage.sources_repo import SourceStatus, get_source, update_source_status
from core.storage.vector_store import ChunkVector, VectorStore
from core.tokens import count_tokens

log = get_logger("ingestion.pipeline")


# 図説明1チャンクの上限トークン数。chunk_document の target_max と揃える。
_FIGURE_DESC_MAX_TOKENS = 800


def _hard_split(text: str, *, max_tokens: int) -> list[str]:
    """チャンカーが分割できなかったテキストを文字数で強制分割する。

    chunk_document は空白・句読点+空白を手掛かりに分割するため、空白を含まない
    日本語がひと続きで来ると1片のまま返る。そのまま埋め込みへ渡すと上限超過で
    Ollama が 500 を返し、取込全体が落ちる(実機FB 2026-07-27 と同じ失敗)。
    ここは最後の防波堤なので、意味的な切れ目は諦めて確実に上限内へ収める。
    """
    pieces: list[str] = []
    rest = text
    while rest:
        window = len(rest)
        # 上限に収まる最大の文字数を、半分ずつ縮めながら探す。
        while window > 1 and count_tokens(rest[:window]) > max_tokens:
            window = max(1, window // 2)
        pieces.append(rest[:window])
        rest = rest[window:]
    return pieces


def _chunk_figure_description(text: str, *, page: int | None) -> list[ChunkOutput]:
    """図説明テキストを通常テキストと同じ規則でチャンク分割する。

    分割結果が空になることはない想定だが、チャンカーが空を返した場合は
    元テキスト1件にフォールバックする(説明を失わない)。
    """
    doc = ParsedDocument(
        title="",
        sections=[ParsedSection(text=text, page=page, heading_path=[], ord=0)],
    )
    pieces = chunk_document(doc)
    if not pieces:
        pieces = [
            ChunkOutput(
                text=text,
                page=page,
                heading_path=[],
                ord=0,
                token_count=count_tokens(text),
            )
        ]

    out: list[ChunkOutput] = []
    for piece in pieces:
        if piece.token_count <= _FIGURE_DESC_MAX_TOKENS:
            out.append(piece)
            continue
        for part in _hard_split(piece.text, max_tokens=_FIGURE_DESC_MAX_TOKENS):
            out.append(
                ChunkOutput(
                    text=part,
                    page=page,
                    heading_path=[],
                    ord=len(out),
                    token_count=count_tokens(part),
                )
            )
    return out


class _GatewayLike(Protocol):
    async def embed(self, *, model: str, text: str) -> list[float]: ...


class _BrokerLike(Protocol):
    async def publish(self, topic: str, payload: dict[str, Any]) -> None: ...


@dataclass
class PipelineDeps:
    conn: sqlite3.Connection
    vector_store: VectorStore
    ollama: _GatewayLike
    embedding_model: str
    broker: _BrokerLike | None = None
    embedding_model_getter: Callable[[], str] | None = None
    # READY 直後に呼ばれる要約フック。失敗しても取込は READY を維持する。
    # アプリ層で SummaryJob.run を asyncio.create_task でラップして渡す想定。
    summary_runner: Callable[[str], Any] | None = None
    assets_dir: Path | None = None
    assets_enabled: Callable[[], bool] | None = None
    figure_describer: Any | None = None  # FigureDescriber プロトコル
    figure_describe_enabled: Callable[[], bool] | None = None
    ocr_engine: Any | None = None  # OcrEngine プロトコル。None ならOCRフォールバックなし


class IngestionPipeline:
    def __init__(self, *, deps: PipelineDeps) -> None:
        self._deps = deps

    def _embedding_model(self) -> str:
        getter = self._deps.embedding_model_getter
        return getter() if getter is not None else self._deps.embedding_model

    def _save_assets(self, conn, *, source_id: str, doc, chunk_records: list[ChunkRecord]) -> None:
        """アセット保存と chunk 紐付け。失敗しても取込全体は継続する(グレースフルデグレード)。"""
        try:
            assets_dir = self._deps.assets_dir / source_id
            by_page_first: dict[int, str] = {}
            for rec in sorted(chunk_records, key=lambda r: r.ord):
                if rec.page is not None and rec.page not in by_page_first:
                    by_page_first[rec.page] = rec.id

            records: list[AssetRecord] = []
            for asset in doc.assets:
                asset_id = new_id()
                chunk_id: str | None = None
                image_path: str | None = None
                if asset.kind == "table" and asset.md_snippet:
                    chunk_id = next(
                        (r.id for r in chunk_records if asset.md_snippet in r.text), None
                    )
                elif asset.kind == "figure":
                    chunk_id = by_page_first.get(asset.page)
                    if asset.image_png:
                        assets_dir.mkdir(parents=True, exist_ok=True)
                        (assets_dir / f"{asset_id}.png").write_bytes(asset.image_png)
                        image_path = f"{source_id}/{asset_id}.png"
                records.append(
                    AssetRecord(
                        id=asset_id,
                        source_id=source_id,
                        chunk_id=chunk_id,
                        kind=asset.kind,
                        page=asset.page,
                        bbox_json=json.dumps(list(asset.bbox)),
                        html=asset.html,
                        md_snippet=asset.md_snippet,
                        image_path=image_path,
                        created_at=datetime.now(UTC).isoformat(),
                    )
                )
            insert_assets(conn, records)
        except Exception:
            log.warning("asset_save_failed", source_id=source_id, exc_info=True)

    async def _describe_figures(
        self,
        conn,
        *,
        source_id: str,
        chunk_records: list[ChunkRecord],
        notebook_id: str,
        on_progress: Callable[[int, int], Any] | None = None,
    ) -> list[ChunkRecord]:
        """未説明の figure アセットを VLM で説明し、独立チャンクとして追加する。
        失敗しても取込全体は継続する(グレースフルデグレード)。

        on_progress(done, total) は figure 1 件ごとに await される。1件あたり
        VLM 推論で数秒かかるため間引きはしない。図が多いPDFではこのフェーズだけで
        数時間に達し、進捗を出さないと status/chunk_count が凍結して「ハングした」
        ようにしか見えない(実機FB 2026-07-26: 1730ページ・図3427件のPDFで
        4時間以上ステータス無変化)。
        """
        from core.storage.assets_repo import list_assets_for_source, set_desc_chunk_link

        new_records: list[ChunkRecord] = []
        try:
            assets = list_assets_for_source(conn, source_id)
            figures = [a for a in assets if a.kind == "figure" and a.desc_chunk_id is None]
            assets_dir = self._deps.assets_dir
            total = len(figures)

            async def _report(done: int) -> None:
                """進捗配信。失敗しても図解析そのものは止めない(表示のための
                副作用が本処理を巻き添えにしないこと)。"""
                if on_progress is None:
                    return
                try:
                    await on_progress(done, total)
                except Exception:
                    log.warning(
                        "figure_progress_publish_failed", source_id=source_id, exc_info=True
                    )

            if total:
                # 開始時点で総数を知らせる(0/N)。これが無いと、1件目の説明が
                # 終わるまで UI は総数すら分からない。
                await _report(0)
            for done, asset in enumerate(figures, start=1):
                try:
                    if not asset.image_path:
                        continue
                    image_path = assets_dir / asset.image_path
                    if not image_path.exists():
                        continue
                    try:
                        text = await self._deps.figure_describer.describe(
                            image_png=image_path.read_bytes()
                        )
                    except Exception:
                        log.warning(
                            "figure_describe_call_failed",
                            source_id=source_id,
                            asset_id=asset.id,
                            exc_info=True,
                        )
                        text = None
                    if not text:
                        continue
                    # 図説明も通常テキストと同じくチャンカーを通す。1図=1チャンクの
                    # ままだと説明が長いときに埋め込みモデルのコンテキスト上限を
                    # 超え、Ollama が 500 を返して取込全体が落ちる(実機FB
                    # 2026-07-27: 2万字の説明で再現)。
                    pieces = _chunk_figure_description(text, page=asset.page)
                    first_chunk_id: str | None = None
                    for piece in pieces:
                        chunk_id = new_id()
                        if first_chunk_id is None:
                            first_chunk_id = chunk_id
                        new_records.append(
                            ChunkRecord(
                                id=chunk_id,
                                source_id=source_id,
                                notebook_id=notebook_id,
                                ord=len(chunk_records) + len(new_records),
                                page=asset.page,
                                heading_path=None,
                                text=piece.text,
                                token_count=piece.token_count,
                                kind="figure_desc",
                            )
                        )
                    if first_chunk_id is None:
                        continue
                    # アセットには先頭チャンクを代表として紐付ける(引用元表示用)。
                    set_desc_chunk_link(conn, asset.id, first_chunk_id)
                finally:
                    # スキップ(画像欠損)・説明失敗も「処理済み」として数える。
                    # finally なので continue しても必ず進捗が出る。
                    await _report(done)
        except Exception:
            log.warning("describe_figures_failed", source_id=source_id, exc_info=True)
        return new_records

    async def describe_existing_figures(self, *, source_id: str) -> None:
        """既存ソースの未解析figureアセットをVLMで説明する(手動「図を解析」用)。
        取込パイプライン外からの呼び出しを想定した公開メソッド。失敗しても例外は
        投げない(呼び出し元は background task なので握りつぶしても実害がない)。"""
        conn = self._deps.conn
        try:
            src = get_source(conn, source_id)
        except Exception:
            log.warning(
                "describe_existing_figures_source_lookup_failed",
                source_id=source_id,
                exc_info=True,
            )
            return
        chunk_records = list_chunks_for_source(conn, source_id)

        async def _figure_progress(done: int, total: int) -> None:
            # 手動「図を解析」も取込と同じ進捗契約で配信する。ソースは既に
            # READY なので status は現在値のまま流し、figures_* だけを載せる。
            if self._deps.broker is None:
                return
            await self._deps.broker.publish(
                f"notebook:{src.notebook_id}",
                {
                    "source_id": source_id,
                    # StrEnum でも素の str でも同じ値になる(repo 実装に依存しない)
                    "status": str(src.status),
                    "figures_done": done,
                    "figures_total": total,
                },
            )

        new_records = await self._describe_figures(
            conn, source_id=source_id, chunk_records=chunk_records, notebook_id=src.notebook_id,
            on_progress=_figure_progress,
        )
        if not new_records:
            return
        insert_chunks(conn, new_records)
        for rec in new_records:
            try:
                vec = await self._deps.ollama.embed(model=self._embedding_model(), text=rec.text)
            except Exception:
                log.warning(
                    "describe_existing_figures_embed_failed",
                    source_id=source_id,
                    chunk_id=rec.id,
                    exc_info=True,
                )
                continue
            self._deps.vector_store.upsert([
                ChunkVector(
                    id=rec.id,
                    vector=vec,
                    notebook_id=rec.notebook_id,
                    source_id=rec.source_id,
                    source_kind=src.kind,
                    page=rec.page,
                    heading_path=rec.heading_path,
                    ord=rec.ord,
                )
            ])

    async def run(self, *, source_id: str, kind: str, data: bytes) -> None:
        conn = self._deps.conn

        async def _publish(status: SourceStatus, **extra: Any) -> None:
            if self._deps.broker is None:
                return
            notebook_id = get_source(conn, source_id).notebook_id
            await self._deps.broker.publish(
                f"notebook:{notebook_id}",
                {"source_id": source_id, "status": status.value, **extra},
            )

        try:
            update_source_status(conn, source_id, status=SourceStatus.PARSING)
            await _publish(SourceStatus.PARSING)
            parser = get_parser(kind)
            extract = (
                kind == "pdf"
                and self._deps.assets_enabled is not None
                and self._deps.assets_enabled()
                and self._deps.assets_dir is not None
            )
            if kind == "pdf":
                doc = await parser.parse_bytes(
                    data,
                    source_hint=get_source(conn, source_id).origin,
                    extract_assets=extract,
                    ocr_engine=self._deps.ocr_engine,
                )
            else:
                doc = parser.parse_bytes(data, source_hint=get_source(conn, source_id).origin)

            update_source_status(conn, source_id, status=SourceStatus.CHUNKING, title=doc.title)
            await _publish(SourceStatus.CHUNKING)
            chunk_outs = chunk_document(doc)
            if not chunk_outs:
                raise AppError(
                    code=ErrorCode.INGESTION_PARSE_FAILED,
                    message="no chunks produced",
                )

            src = get_source(conn, source_id)
            chunk_records = [
                ChunkRecord(
                    id=new_id(),
                    source_id=source_id,
                    notebook_id=src.notebook_id,
                    ord=c.ord,
                    page=c.page,
                    heading_path=" > ".join(c.heading_path) if c.heading_path else None,
                    text=c.text,
                    token_count=c.token_count,
                )
                for c in chunk_outs
            ]
            insert_chunks(conn, chunk_records)

            if extract and doc.assets:
                self._save_assets(
                    conn, source_id=source_id, doc=doc, chunk_records=chunk_records
                )

            describe = (
                extract
                and self._deps.figure_describer is not None
                and self._deps.figure_describe_enabled is not None
                and self._deps.figure_describe_enabled()
            )
            if describe:

                async def _figure_progress(done: int, total: int) -> None:
                    await _publish(
                        SourceStatus.CHUNKING, figures_done=done, figures_total=total
                    )

                desc_records = await self._describe_figures(
                    conn, source_id=source_id, chunk_records=chunk_records,
                    notebook_id=src.notebook_id, on_progress=_figure_progress,
                )
                if desc_records:
                    insert_chunks(conn, desc_records)
                    chunk_records = chunk_records + desc_records

            total = len(chunk_records)
            update_source_status(
                conn,
                source_id,
                status=SourceStatus.EMBEDDING,
                chunk_count=total,
            )
            await _publish(SourceStatus.EMBEDDING, chunk_count=total, embedded=0)
            vectors: list[ChunkVector] = []
            for i, rec in enumerate(chunk_records):
                vec = await self._deps.ollama.embed(model=self._embedding_model(), text=rec.text)
                vectors.append(
                    ChunkVector(
                        id=rec.id,
                        vector=vec,
                        notebook_id=rec.notebook_id,
                        source_id=rec.source_id,
                        source_kind=kind,
                        page=rec.page,
                        heading_path=rec.heading_path,
                        ord=rec.ord,
                    )
                )
                done_n = i + 1
                if done_n == total or done_n % 5 == 0:
                    await _publish(
                        SourceStatus.EMBEDDING, chunk_count=total, embedded=done_n
                    )
            self._deps.vector_store.upsert(vectors)

            page_count = max((c.page or 0 for c in chunk_outs), default=0) or None
            update_source_status(
                conn,
                source_id,
                status=SourceStatus.READY,
                chunk_count=len(chunk_records),
                page_count=page_count,
            )
            await _publish(SourceStatus.READY, chunk_count=len(chunk_records))
            log.info(
                "ingestion_complete",
                source_id=source_id,
                chunk_count=len(chunk_records),
            )

            # Best-effort: 要約フックを呼ぶ。失敗しても READY は維持する。
            if self._deps.summary_runner is not None:
                try:
                    result = self._deps.summary_runner(source_id)
                    if hasattr(result, "__await__"):
                        await result
                except Exception:
                    log.warning("summary_runner_failed", source_id=source_id)

        except AppError as exc:
            # remediation まで保存・配信する。message だけだと「何をすれば直るか」が
            # UI に出ない(実機FB 2026-07-26: 画像PDFの失敗で対処が分からなかった)。
            update_source_status(
                conn,
                source_id,
                status=SourceStatus.ERROR,
                error_msg=exc.message,
                error_remediation=exc.remediation,
            )
            await _publish(
                SourceStatus.ERROR,
                error_msg=exc.message,
                error_remediation=exc.remediation,
            )
            log.error("ingestion_failed", source_id=source_id, code=exc.code, error=exc.message)
        except Exception as exc:  # last-resort safety
            update_source_status(conn, source_id, status=SourceStatus.ERROR, error_msg=str(exc))
            await _publish(SourceStatus.ERROR, error_msg=str(exc))
            log.exception("ingestion_unexpected", source_id=source_id)

"""ノートブック単位の視覚インデックス構築ジョブ (Stage 3, spec §4/§9)。

原本PDFをページレンダリング→視覚埋め込み→pages_visual にupsert。
ページ単位の失敗はログ+スキップで構築継続(部分成功)。
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.logging import get_logger
from core.storage.sources_repo import SourceStatus, list_sources
from core.storage.visual_index_repo import (
    VisualIndexMeta,
    list_indexed_source_ids,
    mark_source_indexed,
    upsert_meta,
)
from core.storage.visual_store import PageVector, VisualPageStore

log = get_logger("visual.index_builder")

# 単一飛行レジストリ(ノートブック単位)。API層(Task 8)が構築中判定に使う。
_BUILDING: set[str] = set()


def is_building(notebook_id: str) -> bool:
    return notebook_id in _BUILDING


def mark_building(notebook_id: str) -> None:
    _BUILDING.add(notebook_id)


def unmark_building(notebook_id: str) -> None:
    _BUILDING.discard(notebook_id)


@dataclass
class BuilderDeps:
    conn: Any
    visual_store: VisualPageStore
    encoder: Any  # VisualEncoder プロトコル
    sources_dir: Path
    assets_dir: Path
    embedding_model_name: str
    render_dpi: int = 100
    progress: Callable[[int, int], Awaitable[None]] | None = None
    # ページ埋め込みバースト間の休止秒(CPU全開の連続実行によるマシン負荷を
    # 緩和する。実機で長時間構築中のBSODを観測したための安全弁)。0で無効。
    page_cooldown_seconds: float = 0.0


@dataclass
class BuildResult:
    indexed_pages: int
    skipped_pages: int
    indexed_sources: int


class VisualIndexBuilder:
    def __init__(self, *, deps: BuilderDeps) -> None:
        self._deps = deps

    def _render_pages(self, pdf_path: Path) -> list[bytes]:
        import pymupdf

        doc = pymupdf.open(pdf_path)
        try:
            return [page.get_pixmap(dpi=self._deps.render_dpi).tobytes("png") for page in doc]
        finally:
            doc.close()

    async def build(self, notebook_id: str) -> BuildResult:
        d = self._deps
        already = list_indexed_source_ids(d.conn, notebook_id)
        targets = [
            s for s in list_sources(d.conn, notebook_id=notebook_id)
            if s.kind == "pdf" and s.status == SourceStatus.READY and s.id not in already
        ]
        built_at = datetime.now(UTC).isoformat()

        # 総ページ数を先に数えて進捗の分母にする(レンダリング失敗ソースは0扱い)
        pages_by_source: dict[str, list[bytes]] = {}
        for s in targets:
            pdf_path = d.sources_dir / f"{s.id}.pdf"
            if not pdf_path.exists():
                log.warning("visual_build_source_missing", source_id=s.id)
                continue
            try:
                pages_by_source[s.id] = self._render_pages(pdf_path)
            except Exception:
                log.warning("visual_build_render_failed", source_id=s.id, exc_info=True)
        total = sum(len(p) for p in pages_by_source.values())

        done = 0
        indexed_pages = 0
        skipped_pages = 0
        indexed_sources = 0
        for s in targets:
            pages = pages_by_source.get(s.id)
            if pages is None:
                continue
            source_indexed = 0
            for page_no, png in enumerate(pages, start=1):
                done += 1
                try:
                    vec = await d.encoder.embed_image(png=png)
                    pages_dir = d.assets_dir / s.id / "pages"
                    pages_dir.mkdir(parents=True, exist_ok=True)
                    (pages_dir / f"{page_no}.png").write_bytes(png)
                    d.visual_store.ensure_collection(dim=len(vec))
                    d.visual_store.upsert_pages([
                        PageVector(
                            source_id=s.id, page=page_no, vector=vec,
                            notebook_id=notebook_id,
                            embedding_model=d.embedding_model_name, built_at=built_at,
                        )
                    ])
                    indexed_pages += 1
                    source_indexed += 1
                except Exception:
                    # ページ単位で失敗しても構築は継続する(spec §9 部分成功)
                    skipped_pages += 1
                    log.warning(
                        "visual_build_page_failed",
                        source_id=s.id, page=page_no, exc_info=True,
                    )
                if d.progress is not None:
                    await d.progress(done, total)
                if d.page_cooldown_seconds > 0 and done < total:
                    await asyncio.sleep(d.page_cooldown_seconds)
            if source_indexed > 0:
                mark_source_indexed(
                    d.conn, notebook_id=notebook_id, source_id=s.id,
                    page_count=source_indexed, built_at=built_at,
                )
                indexed_sources += 1

        if indexed_sources > 0:
            upsert_meta(d.conn, VisualIndexMeta(
                notebook_id=notebook_id,
                embedding_model=d.embedding_model_name,
                built_at=built_at,
            ))
        return BuildResult(
            indexed_pages=indexed_pages,
            skipped_pages=skipped_pages,
            indexed_sources=indexed_sources,
        )

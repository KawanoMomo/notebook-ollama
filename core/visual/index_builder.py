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
from core.storage.visual_store import UnitVector, VisualUnitStore

log = get_logger("visual.index_builder")

# 単一飛行レジストリ((notebook_id, unit) 単位)。API層が構築中判定に使う。
# ページ索引とタイル索引は独立に走らせられる。
_BUILDING: set[tuple[str, str]] = set()


def is_building(notebook_id: str, unit: str = "page") -> bool:
    return (notebook_id, unit) in _BUILDING


def mark_building(notebook_id: str, unit: str = "page") -> None:
    _BUILDING.add((notebook_id, unit))


def unmark_building(notebook_id: str, unit: str = "page") -> None:
    _BUILDING.discard((notebook_id, unit))


@dataclass
class BuilderDeps:
    conn: Any
    visual_store: VisualUnitStore
    encoder: Any  # VisualEncoder プロトコル
    sources_dir: Path
    assets_dir: Path
    embedding_model_name: str
    render_dpi: int = 100
    progress: Callable[[int, int], Awaitable[None]] | None = None
    # ページ埋め込みバースト間の休止秒(CPU全開の連続実行によるマシン負荷を
    # 緩和する。実機で長時間構築中のBSODを観測したための安全弁)。0で無効。
    # タイル単位でも「ページ境界ごと」に挟む — タイル数倍に増やすと構築が
    # 現実的でない長さになる。
    page_cooldown_seconds: float = 0.0
    # --- Stage 4 ---
    unit: str = "page"          # "page" | "tile"
    tile_rows: int = 3
    tile_cols: int = 1
    tile_overlap: float = 0.1


@dataclass
class BuildResult:
    indexed_pages: int
    skipped_pages: int
    indexed_sources: int
    # unit="tile" のとき実際に埋め込んだタイル数。unit="page" では常に 0。
    indexed_tiles: int = 0
    # 今回の構築で対象になった(未索引の READY な PDF)ソース数。
    # レンダリング自体が全ソースで失敗すると indexed_pages も skipped_pages も
    # 増えないため、この件数が無いと「対象なし」と「全滅」を区別できない。
    target_sources: int = 0


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

    def _units_for_page(self, png: bytes) -> list[tuple[int | None, bytes, Path]]:
        """1ページ分の (tile_index, png, 保存相対パス) を返す。

        タイル分割はページ処理の直前に行い、使い終わったら捨てる。全ページを
        先に分割すると pages_by_source の保持バイト数がタイル数倍になり、
        bf16 で常駐約4GB のエンコーダと同居するプロセスで OOM リスクが跳ねる。
        """
        if self._deps.unit != "tile":
            return [(None, png, Path("pages"))]

        from core.visual.tiling import split_tiles

        tiles = split_tiles(
            png,
            rows=self._deps.tile_rows,
            cols=self._deps.tile_cols,
            overlap=self._deps.tile_overlap,
        )
        return [(t.index, t.png, Path("tiles")) for t in tiles]

    def _cooldown_seconds(self) -> float:
        """ページ間クールダウンの実効値。GPU 実行中は 0 にする。

        このクールダウンは CPU 推論の安全弁である(全論理コアAVX全開が
        実質ストレステストになり、実機で長時間構築中に BSOD を観測したため
        導入した。ADR-011 / ECN-003)。GPU ではその負荷は生じないので、
        既定値 10 秒をそのまま適用すると 1ページ 0.4 秒の埋め込みに対して
        10 秒待つことになり、構築が約 20〜30 倍遅くなる(ECN-004 の効果測定で
        実測: 7.5 秒/ページ → 0.44 秒/ページ)。

        判定は `torch.cuda.is_available()` ではなく **エンコーダが実際に載って
        いるデバイス**を見る。ECN-005 のとおり、cuDNN のバージョン衝突下では
        `is_available()` が True のまま演算だけが失敗するため、可用性の問い合わせは
        「GPUで動いている」ことの証拠にならない。ここでは 1 ページ目の埋め込みが
        済んだ後に呼ばれるので、バックエンドはロード済みでデバイスが確定している。

        デバイスを申告しないエンコーダ(テスト用のフェイク等)では None が返るため、
        従来どおり設定値をそのまま使う(安全側)。
        """
        if getattr(self._deps.encoder, "device", None) == "cuda":
            return 0.0
        return self._deps.page_cooldown_seconds

    async def build(self, notebook_id: str) -> BuildResult:
        d = self._deps
        already = list_indexed_source_ids(d.conn, notebook_id, d.unit)
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
        indexed_tiles = 0
        for s in targets:
            pages = pages_by_source.get(s.id)
            if pages is None:
                continue
            source_indexed = 0
            for page_no, png in enumerate(pages, start=1):
                done += 1
                page_units = 0
                try:
                    # タイル分割は同期の画像処理。イベントループを塞がないよう
                    # スレッドへ逃がす(このジョブは BackgroundTasks =
                    # 同一イベントループで走る)。
                    units = await asyncio.to_thread(self._units_for_page, png)
                except Exception:
                    # 分割自体の失敗はページ全体の失敗(spec §9 部分成功)
                    units = []
                    log.warning(
                        "visual_build_split_failed",
                        source_id=s.id, page=page_no, unit=d.unit, exc_info=True,
                    )
                # 例外ハンドラは「単位ごと」に置く。ページ内タイルループ全体を
                # 1つの try で囲うと、先頭タイルの失敗で同じページの残りタイルが
                # 丸ごと捨てられる(3分割なら1件の失敗で良好な2件を失う)。
                # spec §9 の部分成功は単位ごとの独立性を意図している。
                for tile_index, unit_png, subdir in units:
                    try:
                        vec = await d.encoder.embed_image(png=unit_png)
                        out_dir = d.assets_dir / s.id / subdir
                        out_dir.mkdir(parents=True, exist_ok=True)
                        name = (
                            f"{page_no}.png" if tile_index is None
                            else f"{page_no}-{tile_index}.png"
                        )
                        (out_dir / name).write_bytes(unit_png)
                        d.visual_store.ensure_collection(dim=len(vec))
                        d.visual_store.upsert_units([
                            UnitVector(
                                source_id=s.id, page=page_no, vector=vec,
                                notebook_id=notebook_id,
                                embedding_model=d.embedding_model_name,
                                built_at=built_at, tile_index=tile_index,
                            )
                        ])
                        page_units += 1
                    except Exception:
                        log.warning(
                            "visual_build_unit_failed",
                            source_id=s.id, page=page_no,
                            unit=d.unit, tile_index=tile_index, exc_info=True,
                        )
                if d.unit == "tile":
                    indexed_tiles += page_units
                if page_units > 0:
                    indexed_pages += 1
                    source_indexed += 1
                else:
                    skipped_pages += 1
                if d.progress is not None:
                    await d.progress(done, total)
                if self._cooldown_seconds() > 0 and done < total:
                    await asyncio.sleep(self._cooldown_seconds())
            if source_indexed > 0:
                mark_source_indexed(
                    d.conn, notebook_id=notebook_id, source_id=s.id,
                    page_count=source_indexed, built_at=built_at, unit=d.unit,
                )
                indexed_sources += 1

        if indexed_sources > 0:
            upsert_meta(d.conn, VisualIndexMeta(
                notebook_id=notebook_id,
                embedding_model=d.embedding_model_name,
                built_at=built_at,
                unit=d.unit,
            ))
        return BuildResult(
            indexed_pages=indexed_pages,
            skipped_pages=skipped_pages,
            indexed_sources=indexed_sources,
            indexed_tiles=indexed_tiles,
            target_sources=len(targets),
        )

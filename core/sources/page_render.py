"""PDF ページのオンデマンド描画とディスクキャッシュ。

設計: docs/specs/2026-08-07-citation-evidence-ui-design.md §3.4

事前生成はしない(索引サイズと ingest 時間を増やさないため)。押されたページだけ
描画し、`<data_dir>/cache/pages/{source_id}/{page}@{dpi}.png` に貯める。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pymupdf

# 自由入力を許すと 1 リクエストで数十 MB を生成でき、ディスクを無制限に食う。
ALLOWED_DPI = frozenset({150, 300})


class UnsupportedDpiError(ValueError):
    """許可リスト外の dpi。"""


def cache_path_for(cache_dir: Path, source_id: str, page: int, dpi: int) -> Path:
    return cache_dir / source_id / f"{page}@{dpi}.png"


def purge_source_cache(cache_dir: Path, source_id: str) -> None:
    """そのソースのページ画像キャッシュだけを消す(他ソースには触れない)。"""
    shutil.rmtree(cache_dir / source_id, ignore_errors=True)


def render_page_png(*, pdf_path: Path, page: int, dpi: int, cache_dir: Path) -> bytes:
    """1 起算のページ番号を PNG バイト列にする。キャッシュがあればそれを返す。

    キャッシュキーには PDF のファイル名(= source_id)を使う。同じソースの PDF が
    差し替わることは無い(再取込は別 source_id になる)ため、内容ハッシュは取らない。
    """
    if dpi not in ALLOWED_DPI:
        raise UnsupportedDpiError(f"dpi must be one of {sorted(ALLOWED_DPI)}: {dpi}")

    cached = cache_path_for(cache_dir, pdf_path.stem, page, dpi)
    if cached.exists():
        return cached.read_bytes()

    with pymupdf.open(pdf_path) as doc:
        if page < 1 or page > doc.page_count:
            raise IndexError(f"page out of range: {page} (1..{doc.page_count})")
        data: bytes = doc[page - 1].get_pixmap(dpi=dpi).tobytes("png")

    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    return data

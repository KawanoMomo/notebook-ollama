from __future__ import annotations

from core.ingestion.types import ParsedAsset
from core.logging import get_logger

log = get_logger("ingestion.pdf_assets")

_MIN_FIGURE_AREA_RATIO = 0.005   # ページ面積の0.5%未満は微小画像として除外
_MAX_FIGURE_AREA_RATIO = 0.9     # ほぼ全面は背景画像として除外
_CROP_DPI = 150


def _cell(v) -> str:
    return (v or "").replace("\n", " ").strip()


def has_merged_cells(rows: list[list]) -> bool:
    return any(cell is None for row in rows for cell in row)


def table_to_markdown(rows: list[list]) -> str:
    if not rows:
        return ""
    header = [_cell(c) for c in rows[0]]
    lines = ["| " + " | ".join(header) + " |",
             "| " + " | ".join("---" for _ in header) + " |"]
    for row in rows[1:]:
        lines.append("| " + " | ".join(_cell(c) for c in row) + " |")
    return "\n".join(lines)


def table_to_html(rows: list[list]) -> str:
    import html as _html
    out = ["<table>"]
    for ri, row in enumerate(rows):
        tag = "th" if ri == 0 else "td"
        cells = "".join(
            f"<{tag}>{_html.escape(_cell(c))}</{tag}>" for c in row if c is not None
        )
        out.append(f"<tr>{cells}</tr>")
    out.append("</table>")
    return "".join(out)


def extract_page_assets(page, page_number: int) -> list[ParsedAsset]:
    """1ページ分の表・図アセットを抽出。失敗はページ単位でログ+スキップ。"""
    assets: list[ParsedAsset] = []
    try:
        for table in page.find_tables().tables:
            rows = table.extract()
            if not rows:
                continue
            assets.append(ParsedAsset(
                kind="table",
                page=page_number,
                bbox=tuple(table.bbox),
                html=table_to_html(rows),
                md_snippet=table_to_markdown(rows),
            ))
    except Exception:
        log.warning("table_extract_failed", page=page_number, exc_info=True)
    try:
        page_area = abs(page.rect)
        for info in page.get_image_info():
            import pymupdf
            bbox = pymupdf.Rect(info["bbox"])
            ratio = abs(bbox) / page_area if page_area else 0
            if ratio < _MIN_FIGURE_AREA_RATIO or ratio > _MAX_FIGURE_AREA_RATIO:
                continue
            pix = page.get_pixmap(clip=bbox, dpi=_CROP_DPI)
            assets.append(ParsedAsset(
                kind="figure",
                page=page_number,
                bbox=(bbox.x0, bbox.y0, bbox.x1, bbox.y1),
                image_png=pix.tobytes("png"),
            ))
    except Exception:
        log.warning("figure_extract_failed", page=page_number, exc_info=True)
    return assets


def page_text_excluding(page, exclude_bboxes: list[tuple]) -> str:
    """表領域と過半重なるテキストブロックを除外した本文テキスト。"""
    import pymupdf
    excl = [pymupdf.Rect(b) for b in exclude_bboxes]

    def overlaps(rect: pymupdf.Rect) -> bool:
        for e in excl:
            inter = rect & e
            if not inter.is_empty and abs(inter) > abs(rect) * 0.5:
                return True
        return False

    blocks = page.get_text("blocks")  # (x0,y0,x1,y1,text,block_no,block_type)
    kept = [b[4] for b in sorted(blocks, key=lambda b: (b[1], b[0]))
            if b[6] == 0 and not overlaps(pymupdf.Rect(b[:4]))]
    return "\n".join(t.strip() for t in kept if t.strip())

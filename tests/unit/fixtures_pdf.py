"""合成PDF生成(PyMuPDF)。罫線あり表 = 矩形グリッド + セル文字列。"""
from __future__ import annotations

import pymupdf


def build_pdf_with_table(rows: list[list[str]], *, body_text: str = "前段の本文です。") -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 80), body_text, fontsize=11, fontname="japan")
    x0, y0, cell_w, cell_h = 72, 120, 120, 24
    for ri, row in enumerate(rows):
        for ci, cell in enumerate(row):
            rect = pymupdf.Rect(
                x0 + ci * cell_w, y0 + ri * cell_h,
                x0 + (ci + 1) * cell_w, y0 + (ri + 1) * cell_h,
            )
            page.draw_rect(rect, color=(0, 0, 0), width=0.7)
            page.insert_text((rect.x0 + 4, rect.y1 - 8), cell, fontsize=10, fontname="japan")
    page.insert_text(
        (72, y0 + len(rows) * cell_h + 40), "後段の本文です。", fontsize=11, fontname="japan"
    )
    data = doc.tobytes()
    doc.close()
    return data


def build_pdf_with_image(*, img_size: tuple[int, int] = (200, 150)) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 80), "図の説明が書かれた本文。", fontsize=11, fontname="japan")
    pm = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, *img_size), False)
    pm.set_rect(pm.irect, (200, 60, 60))
    page.insert_image(pymupdf.Rect(72, 120, 72 + img_size[0], 120 + img_size[1]),
                      pixmap=pm)
    data = doc.tobytes()
    doc.close()
    return data

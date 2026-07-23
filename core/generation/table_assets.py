"""生成コンテキスト用: 結合セルを含む表のみ Markdown→HTML 置換する。

単純表は Markdown のまま(トークン節約)。結合セル判定は「Markdown セル数と
HTML セル数の不一致」で行う(結合セルは Markdown 平坦化で空セルが増えるため)。
"""
from __future__ import annotations

import re

from core.storage.assets_repo import AssetRecord

_MD_ROW = re.compile(r"^\|.*\|$", re.MULTILINE)
_MD_SEP = re.compile(r"^\|[\s\-|]+\|$")


def _md_cell_count(md: str) -> int:
    n = 0
    for line in md.splitlines():
        if _MD_ROW.match(line.strip()) and not _MD_SEP.match(line.strip()):
            n += line.count("|") - 1
    return n


def _html_cell_count(html: str) -> int:
    return html.count("<td>") + html.count("<th>")


def substitute_table_html(text: str, assets: list[AssetRecord]) -> str:
    for a in assets:
        if a.kind != "table" or not a.md_snippet or not a.html:
            continue
        if a.md_snippet not in text:
            continue
        if _md_cell_count(a.md_snippet) != _html_cell_count(a.html):
            text = text.replace(a.md_snippet, a.html, 1)
    return text

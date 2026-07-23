from core.generation.table_assets import substitute_table_html
from core.storage.assets_repo import AssetRecord


def _asset(md, html):
    return AssetRecord(id="a", source_id="s", chunk_id="c", kind="table", page=1,
                       bbox_json=None, html=html, md_snippet=md, image_path=None,
                       created_at="")


SIMPLE_MD = "| A | B |\n| --- | --- |\n| 1 | 2 |"
SIMPLE_HTML = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
# 結合セル: Markdownは4セルに平坦化されるがHTMLは3セル
MERGED_MD = "| A | B |\n| --- | --- |\n| 1 |  |"
MERGED_HTML = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td></tr></table>"


def test_simple_table_kept_as_markdown():
    text = f"前文\n\n{SIMPLE_MD}\n\n後文"
    assert substitute_table_html(text, [_asset(SIMPLE_MD, SIMPLE_HTML)]) == text


def test_merged_cell_table_replaced_with_html():
    text = f"前文\n\n{MERGED_MD}\n\n後文"
    out = substitute_table_html(text, [_asset(MERGED_MD, MERGED_HTML)])
    assert MERGED_HTML in out and MERGED_MD not in out


def test_missing_snippet_is_noop():
    assert substitute_table_html("無関係", [_asset(SIMPLE_MD, SIMPLE_HTML)]) == "無関係"


def test_figure_assets_ignored():
    fig = AssetRecord(id="f", source_id="s", chunk_id="c", kind="figure", page=1,
                      bbox_json=None, html=None, md_snippet=None,
                      image_path="s/f.png", created_at="")
    assert substitute_table_html("本文", [fig]) == "本文"

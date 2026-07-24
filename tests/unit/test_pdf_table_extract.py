import pytest

pymupdf = pytest.importorskip("pymupdf")
pytestmark = pytest.mark.pdf

from core.ingestion.parsers.pdf import PdfParser  # noqa: E402
from tests.unit.fixtures_pdf import build_pdf_with_table  # noqa: E402

ROWS = [["品名", "数量"], ["ネジ", "10"], ["ナット", "20"]]


async def test_table_extracted_as_asset_and_markdown_in_body():
    data = build_pdf_with_table(ROWS)
    doc = await PdfParser().parse_bytes(data, extract_assets=True)
    tables = [a for a in doc.assets if a.kind == "table"]
    assert len(tables) == 1
    t = tables[0]
    assert "ネジ" in t.md_snippet and "| 品名 | 数量 |" in t.md_snippet
    assert "<table>" in t.html and "<td>10</td>" in t.html
    body = "\n".join(s.text for s in doc.sections)
    assert t.md_snippet in body            # Markdown表が本文に挿入されている
    assert "前段の本文です。" in body
    # 表セル文字列が生テキストとして二重に残っていない(表領域は除外)
    assert body.count("ネジ") == 1


async def test_extract_assets_false_keeps_legacy_behavior():
    data = build_pdf_with_table(ROWS)
    doc = await PdfParser().parse_bytes(data, extract_assets=False)
    assert doc.assets == []
    assert "ネジ" in "\n".join(s.text for s in doc.sections)  # 従来どおり生テキスト

from core.ingestion.parsers.markdown import MarkdownParser

SAMPLE = """\
# Title

Intro paragraph.

## Section 1

Body of section 1.

### Sub 1.1

Sub content.

## Section 2

Body of section 2.
"""


def test_markdown_parser_splits_by_heading():
    p = MarkdownParser()
    doc = p.parse_bytes(SAMPLE.encode("utf-8"), source_hint="doc.md")
    assert doc.title == "Title"
    headings = [s.heading_path for s in doc.sections]
    assert ["Title"] in headings
    assert ["Title", "Section 1"] in headings
    assert ["Title", "Section 1", "Sub 1.1"] in headings
    assert ["Title", "Section 2"] in headings


def test_markdown_parser_ord_is_monotonic():
    p = MarkdownParser()
    doc = p.parse_bytes(SAMPLE.encode("utf-8"))
    ords = [s.ord for s in doc.sections]
    assert ords == sorted(ords)


def test_markdown_parser_handles_no_heading():
    p = MarkdownParser()
    doc = p.parse_bytes(b"just text\nno heading")
    assert len(doc.sections) == 1
    assert doc.sections[0].text.strip().startswith("just text")

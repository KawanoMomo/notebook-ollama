from pathlib import Path

from core.ingestion.parsers.docx import DocxParser

FIXTURE = Path(__file__).parents[2] / "fixtures" / "sample.docx"


def test_docx_parser_extracts_headings_and_paragraphs():
    p = DocxParser()
    doc = p.parse_bytes(FIXTURE.read_bytes(), source_hint="doc.docx")
    assert doc.title == "Document Title"
    body = " ".join(s.text for s in doc.sections)
    assert "Intro paragraph" in body
    assert "Body of section A" in body
    assert "Body of section B" in body


def test_docx_parser_heading_paths_track_hierarchy():
    p = DocxParser()
    doc = p.parse_bytes(FIXTURE.read_bytes())
    paths = [tuple(s.heading_path) for s in doc.sections]
    assert ("Document Title", "Section A") in paths
    assert ("Document Title", "Section B") in paths

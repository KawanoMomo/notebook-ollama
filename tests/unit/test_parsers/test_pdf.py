from pathlib import Path

from core.ingestion.parsers.pdf import PdfParser

FIXTURE = Path(__file__).parents[2] / "fixtures" / "sample.pdf"


def test_pdf_parser_emits_one_section_per_page():
    p = PdfParser()
    doc = p.parse_bytes(FIXTURE.read_bytes(), source_hint="doc.pdf")
    pages = [s.page for s in doc.sections]
    assert pages == [1, 2]


def test_pdf_parser_extracts_text_per_page():
    p = PdfParser()
    doc = p.parse_bytes(FIXTURE.read_bytes())
    assert "page one" in doc.sections[0].text.lower()
    assert "page two" in doc.sections[1].text.lower()

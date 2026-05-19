from pathlib import Path
from core.ingestion.parsers.web import WebParser

FIXTURE = Path(__file__).parents[2] / "fixtures" / "sample.html"

def test_web_parser_extracts_title_and_body():
    p = WebParser()
    doc = p.parse_bytes(FIXTURE.read_bytes(), source_hint="https://example.com/sample")
    assert doc.title == "Sample Article"
    body = " ".join(s.text for s in doc.sections)
    assert "First paragraph" in body
    assert "Second paragraph" in body

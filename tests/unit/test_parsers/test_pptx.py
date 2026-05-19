from pathlib import Path
from core.ingestion.parsers.pptx import PptxParser

FIXTURE = Path(__file__).parents[2] / "fixtures" / "sample.pptx"

def test_pptx_parser_one_section_per_slide():
    p = PptxParser()
    doc = p.parse_bytes(FIXTURE.read_bytes(), source_hint="deck.pptx")
    pages = [s.page for s in doc.sections]
    assert pages == [1, 2]

def test_pptx_parser_includes_speaker_notes():
    p = PptxParser()
    doc = p.parse_bytes(FIXTURE.read_bytes())
    assert "Speaker note one" in doc.sections[0].text

def test_pptx_parser_uses_slide_title_as_heading():
    p = PptxParser()
    doc = p.parse_bytes(FIXTURE.read_bytes())
    assert doc.sections[0].heading_path == ["Slide One"]
    assert doc.sections[1].heading_path == ["Slide Two"]

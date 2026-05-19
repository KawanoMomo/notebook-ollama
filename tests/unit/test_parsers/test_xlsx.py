from pathlib import Path

from core.ingestion.parsers.xlsx import XlsxParser

FIXTURE = Path(__file__).parents[2] / "fixtures" / "sample.xlsx"


def test_xlsx_parser_one_section_per_sheet():
    p = XlsxParser()
    doc = p.parse_bytes(FIXTURE.read_bytes(), source_hint="book.xlsx")
    assert [s.heading_path[0] for s in doc.sections] == ["Specs", "Notes"]


def test_xlsx_parser_serializes_rows_as_csv_lines():
    p = XlsxParser()
    doc = p.parse_bytes(FIXTURE.read_bytes())
    text = "\n".join(s.text for s in doc.sections)
    assert "Name,Value" in text
    assert "Vdd,3.3V" in text
    assert "MCU,Cortex-M4" in text

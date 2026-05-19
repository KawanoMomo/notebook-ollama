from core.ingestion.parsers.txt import TxtParser

def test_txt_parser_emits_single_section():
    p = TxtParser()
    doc = p.parse_bytes("Hello\n\nWorld".encode("utf-8"), source_hint="memo.txt")
    assert doc.title == "memo.txt"
    assert len(doc.sections) == 1
    assert "Hello" in doc.sections[0].text

def test_txt_parser_handles_bom():
    p = TxtParser()
    raw = "﻿hello".encode("utf-8")
    doc = p.parse_bytes(raw)
    assert doc.sections[0].text.lstrip("﻿") == "hello" or doc.sections[0].text == "hello"

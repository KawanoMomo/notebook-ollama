from core.ingestion.chunker import chunk_document
from core.ingestion.types import ParsedDocument, ParsedSection


def _section(text: str, page=None, heading=None, ord_=0) -> ParsedSection:
    return ParsedSection(text=text, page=page, heading_path=heading or [], ord=ord_)


def test_short_section_becomes_single_chunk():
    doc = ParsedDocument(title="T", sections=[_section("Hello world.")])
    chunks = chunk_document(doc, target_min=200, target_max=800)
    assert len(chunks) == 1
    assert chunks[0].text == "Hello world."
    assert chunks[0].token_count > 0


def test_long_section_is_split_into_multiple_chunks():
    long_text = ("Lorem ipsum dolor sit amet. " * 500).strip()
    doc = ParsedDocument(title="T", sections=[_section(long_text, page=1, heading=["Ch1"])])
    chunks = chunk_document(doc, target_min=200, target_max=400)
    assert len(chunks) > 1
    for c in chunks:
        assert c.heading_path == ["Ch1"]
        assert c.page == 1
        assert c.token_count <= 600


def test_multiple_short_sections_keep_separate_chunks_per_heading():
    doc = ParsedDocument(
        title="T",
        sections=[
            _section("A short A.", heading=["Ch1"], ord_=0),
            _section("A short B.", heading=["Ch2"], ord_=1),
        ],
    )
    chunks = chunk_document(doc, target_min=10, target_max=400)
    assert len(chunks) == 2
    assert chunks[0].heading_path == ["Ch1"]
    assert chunks[1].heading_path == ["Ch2"]


def test_chunks_keep_ord_increasing():
    doc = ParsedDocument(
        title="T",
        sections=[
            _section("hello " * 100, ord_=0),
            _section("world " * 100, ord_=1),
        ],
    )
    chunks = chunk_document(doc, target_min=10, target_max=80)
    ords = [c.ord for c in chunks]
    assert ords == sorted(ords)

from core.generation.citations import CitationSpec, build_citations, find_citation_numbers


def test_find_citation_numbers_simple():
    assert find_citation_numbers("hello [^1] world [^2]") == [1, 2]


def test_find_citation_numbers_dedup_preserve_order():
    assert find_citation_numbers("[^1][^2][^1][^3]") == [1, 2, 3]


def test_find_citation_numbers_ignores_unrelated_brackets():
    assert find_citation_numbers("[1] [foo] [^x] hi [^5]") == [5]


def test_build_citations_resolves_mapping():
    specs = {
        1: CitationSpec(
            chunk_id="c1",
            source_id="s1",
            source_title="ARM",
            location="p.42",
            url_or_path="arm.pdf",
            snippet="snip 1",
        ),
        2: CitationSpec(
            chunk_id="c2",
            source_id="s2",
            source_title="Memo",
            location="§3",
            url_or_path=None,
            snippet="snip 2",
        ),
    }
    result = build_citations(answer="hello [^1] [^2]", specs=specs)
    assert result == [
        {
            "n": 1,
            "chunk_id": "c1",
            "source_id": "s1",
            "source_title": "ARM",
            "location": "p.42",
            "url_or_path": "arm.pdf",
            "snippet": "snip 1",
        },
        {
            "n": 2,
            "chunk_id": "c2",
            "source_id": "s2",
            "source_title": "Memo",
            "location": "§3",
            "url_or_path": None,
            "snippet": "snip 2",
        },
    ]

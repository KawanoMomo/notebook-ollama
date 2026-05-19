from core.ingestion.parsers import get_parser, known_kinds


def test_registry_has_all_kinds():
    assert set(known_kinds()) >= {"txt", "markdown", "web", "pdf", "docx", "pptx", "xlsx"}


def test_get_parser_returns_correct_kind():
    for kind in known_kinds():
        assert get_parser(kind).kind == kind

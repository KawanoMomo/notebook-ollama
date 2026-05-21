from apps.api.routers.sources import _detect_url_kind


def test_pdf_via_content_type():
    assert (
        _detect_url_kind(
            url="https://x.test/file",
            content_type="application/pdf",
            data=b"%PDF-1.4\n...",
        )
        == "pdf"
    )


def test_pdf_via_magic_bytes_when_content_type_missing():
    assert _detect_url_kind(url="https://x.test/foo", content_type=None, data=b"%PDF-1.7\n...") == "pdf"


def test_pdf_via_url_extension_when_server_returns_octet_stream():
    assert (
        _detect_url_kind(
            url="https://www.autosar.org/x/AUTOSAR_CP_SWS_I2CDriver.pdf",
            content_type="application/octet-stream",
            data=b"%PDF-1.5\n...",
        )
        == "pdf"
    )


def test_html_defaults_to_web():
    assert (
        _detect_url_kind(
            url="https://example.com/article",
            content_type="text/html; charset=utf-8",
            data=b"<html>...",
        )
        == "web"
    )


def test_markdown_via_content_type():
    assert (
        _detect_url_kind(
            url="https://example.com/README",
            content_type="text/markdown",
            data=b"# Title\n",
        )
        == "markdown"
    )


def test_url_extension_takes_priority_over_text_plain():
    """text/plain is too generic; URL ext should refine when present."""
    assert (
        _detect_url_kind(
            url="https://example.com/foo.md",
            content_type=None,
            data=b"# header",
        )
        == "markdown"
    )


def test_unknown_falls_back_to_web():
    assert (
        _detect_url_kind(url="https://example.com/", content_type=None, data=b"\x00\x01\x02")
        == "web"
    )

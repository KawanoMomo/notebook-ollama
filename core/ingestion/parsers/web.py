from __future__ import annotations

import trafilatura
from trafilatura.settings import use_config

from core.exceptions import AppError, ErrorCode
from core.ingestion.parsers import register
from core.ingestion.types import ParsedDocument, ParsedSection


def _config():
    cfg = use_config()
    cfg.set("DEFAULT", "EXTRACTION_TIMEOUT", "30")
    return cfg


class WebParser:
    kind = "web"

    def parse_bytes(self, data: bytes, *, source_hint: str | None = None) -> ParsedDocument:
        html = data.decode("utf-8", errors="replace")
        cfg = _config()
        metadata = trafilatura.extract_metadata(html)
        title = (metadata.title if metadata and metadata.title else None) or (
            source_hint or "web page"
        )
        extracted = trafilatura.extract(
            html,
            config=cfg,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )
        if not extracted:
            raise AppError(
                ErrorCode.INGESTION_PARSE_FAILED,
                "could not extract readable content from HTML",
            )
        sections = [
            ParsedSection(text=extracted, page=None, heading_path=[title], ord=0)
        ]
        return ParsedDocument(title=title, sections=sections)


register(WebParser())

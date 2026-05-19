from __future__ import annotations

from core.ingestion.parsers import register
from core.ingestion.types import ParsedDocument, ParsedSection


class TxtParser:
    kind = "txt"

    def parse_bytes(self, data: bytes, *, source_hint: str | None = None) -> ParsedDocument:
        text = data.decode("utf-8", errors="replace").lstrip("﻿")
        title = source_hint or "text"
        return ParsedDocument(
            title=title,
            sections=[ParsedSection(text=text, page=None, heading_path=[], ord=0)],
        )


register(TxtParser())

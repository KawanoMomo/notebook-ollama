from __future__ import annotations

import pymupdf

from core.exceptions import AppError, ErrorCode
from core.ingestion.parsers import register
from core.ingestion.types import ParsedDocument, ParsedSection


class PdfParser:
    kind = "pdf"

    def parse_bytes(self, data: bytes, *, source_hint: str | None = None) -> ParsedDocument:
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:
            raise AppError(
                ErrorCode.INGESTION_PARSE_FAILED, "PDF parse failed", detail=str(exc)
            ) from exc

        sections: list[ParsedSection] = []
        for page_index, page in enumerate(doc):
            text = page.get_text("text") or ""
            text = text.strip()
            if not text:
                continue
            sections.append(
                ParsedSection(
                    text=text,
                    page=page_index + 1,
                    heading_path=[],
                    ord=page_index,
                )
            )
        title = (doc.metadata.get("title") if doc.metadata else None) or (
            source_hint or "document.pdf"
        )
        doc.close()
        if not sections:
            raise AppError(
                ErrorCode.INGESTION_PARSE_FAILED,
                "no extractable text in PDF (image-only?)",
            )
        return ParsedDocument(title=title, sections=sections)


register(PdfParser())

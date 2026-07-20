from __future__ import annotations

from core.exceptions import AppError, ErrorCode
from core.ingestion.parsers import register
from core.ingestion.types import ParsedAsset, ParsedDocument, ParsedSection


class PdfParser:
    kind = "pdf"

    def parse_bytes(
        self, data: bytes, *, source_hint: str | None = None, extract_assets: bool = False
    ) -> ParsedDocument:
        try:
            import pymupdf  # type: ignore[import-not-found]
        except ImportError as exc:
            raise AppError(
                ErrorCode.INGESTION_DEP_MISSING,
                "PDF パーサ (PyMuPDF) が未インストールです",
                detail=str(exc),
                remediation=(
                    "scripts/install-pdf-support.sh または "
                    "scripts/install-pdf-support.ps1 を実行してください "
                    "(PyMuPDF は AGPL-3.0 ライセンスのため同意が必要)"
                ),
            ) from exc

        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:
            raise AppError(
                ErrorCode.INGESTION_PARSE_FAILED, "PDF parse failed", detail=str(exc)
            ) from exc

        sections: list[ParsedSection] = []
        assets: list[ParsedAsset] = []
        for page_index, page in enumerate(doc):
            page_no = page_index + 1
            if extract_assets:
                from core.ingestion import pdf_assets

                page_assets = pdf_assets.extract_page_assets(page, page_no)
                table_bboxes = [a.bbox for a in page_assets if a.kind == "table"]
                text = pdf_assets.page_text_excluding(page, table_bboxes)
                # Markdown表を独立段落として末尾に挿入(chunkerは \n{2,} で分割)
                md_blocks = [a.md_snippet for a in page_assets if a.kind == "table"]
                text = "\n\n".join(t for t in [text, *md_blocks] if t)
                assets.extend(page_assets)
            else:
                text = (page.get_text("text") or "").strip()
            if not text.strip():
                continue
            sections.append(
                ParsedSection(
                    text=text.strip(),
                    page=page_no,
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
        return ParsedDocument(title=title, sections=sections, assets=assets)


register(PdfParser())

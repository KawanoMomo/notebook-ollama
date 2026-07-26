from __future__ import annotations

from typing import Any

from core.exceptions import AppError, ErrorCode
from core.ingestion.parsers import register
from core.ingestion.types import ParsedAsset, ParsedDocument, ParsedSection


class PdfParser:
    kind = "pdf"

    async def parse_bytes(
        self,
        data: bytes,
        *,
        source_hint: str | None = None,
        extract_assets: bool = False,
        ocr_engine: Any | None = None,
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
        if not sections:
            # 無効な OCR エンジンは全ページ None を返すだけなので、「OCRを
            # 試していない」状態と「試したが読めなかった」状態を区別する。
            # 区別しないと、ベータOFF時に一度もOCRしていないのに
            # 「OCRでも読み取れませんでした」と表示される(実機FB 2026-07-26)。
            probe = getattr(ocr_engine, "is_available", None)
            ocr_usable = ocr_engine is not None and (probe is None or bool(probe()))
            if not ocr_usable:
                doc.close()
                raise AppError(
                    ErrorCode.INGESTION_PARSE_FAILED,
                    "このPDFにはテキストが含まれていません(全ページが画像のようです)",
                    remediation=(
                        "スキャンPDFを取り込むには、別のツール(Acrobat・Googleドライブ等)で"
                        "OCRしてテキスト付きPDFに変換してから追加してください。"
                    ),
                )
            ocr_sections: list[ParsedSection] = []
            for page_index, page in enumerate(doc):
                pix = page.get_pixmap(dpi=150)
                text = await ocr_engine.ocr_page(image_png=pix.tobytes("png"))
                if text:
                    ocr_sections.append(
                        ParsedSection(
                            text=text, page=page_index + 1, heading_path=[], ord=page_index,
                        )
                    )
            doc.close()
            if not ocr_sections:
                # 実機FB 2026-07-26: 「設定を確認してください」は行き止まりだった。
                # 視覚モデルは設定済みで、問題は設定ではなく小型VLMのOCR能力。
                # 11GB級の環境で実用になるOCRモデルが無いことを正直に伝え、
                # 実際に前に進める手段(外部OCR)を案内する。
                raise AppError(
                    ErrorCode.INGESTION_PARSE_FAILED,
                    "このPDFは全ページが画像で、OCRでも文字を読み取れませんでした",
                    remediation=(
                        "別のツール(Acrobat・Googleドライブ等)でOCRしてテキスト付き"
                        "PDFに変換してから取り込んでください。"
                        "ローカルの視覚モデルによるOCRは、小型モデルでは実用的な精度に"
                        "届かないことがあります。"
                    ),
                )
            sections = ocr_sections
        else:
            doc.close()
        return ParsedDocument(title=title, sections=sections, assets=assets)


register(PdfParser())

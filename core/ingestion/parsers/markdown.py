from __future__ import annotations

from markdown_it import MarkdownIt

from core.ingestion.parsers import register
from core.ingestion.types import ParsedDocument, ParsedSection


class MarkdownParser:
    kind = "markdown"

    def parse_bytes(self, data: bytes, *, source_hint: str | None = None) -> ParsedDocument:
        text = data.decode("utf-8", errors="replace")
        md = MarkdownIt("commonmark")
        tokens = md.parse(text)

        title = source_hint or "document"
        heading_stack: list[tuple[int, str]] = []  # (level, label)
        sections: list[ParsedSection] = []
        buffer: list[str] = []
        ord_ = 0

        def flush() -> None:
            nonlocal buffer, ord_
            body = "\n".join(buffer).strip()
            if not body and not heading_stack:
                return
            path = [label for _, label in heading_stack]
            if not path and not body:
                return
            sections.append(
                ParsedSection(
                    text=body,
                    page=None,
                    heading_path=path,
                    ord=ord_,
                )
            )
            ord_ += 1
            buffer = []

        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok.type == "heading_open":
                # flush current buffer before changing heading
                flush()
                level = int(tok.tag[1])
                # next token is inline with heading text
                label = tokens[i + 1].content if i + 1 < len(tokens) else ""
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                heading_stack.append((level, label))
                if level == 1 and title == (source_hint or "document"):
                    title = label or title
                i += 3  # heading_open, inline, heading_close
                continue
            if tok.type == "inline":
                buffer.append(tok.content)
            elif tok.type in {"paragraph_open", "paragraph_close", "softbreak"}:
                pass
            elif tok.content:
                buffer.append(tok.content)
            i += 1
        flush()

        if not sections:
            sections.append(ParsedSection(text=text.strip(), heading_path=[], ord=0))

        return ParsedDocument(title=title, sections=sections)


register(MarkdownParser())

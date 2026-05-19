from __future__ import annotations

import re
from dataclasses import dataclass

from core.ingestion.types import ParsedDocument, ParsedSection
from core.tokens import count_tokens

_SENT_SPLIT = re.compile(r"(?<=[。．！？\.\!\?])\s+|\n{2,}")


@dataclass
class ChunkOutput:
    text: str
    page: int | None
    heading_path: list[str]
    ord: int
    token_count: int


def _split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_SPLIT.split(text) if p and p.strip()]
    return parts or [text]


def _pack(
    sentences: list[str],
    *,
    page: int | None,
    heading: list[str],
    start_ord: int,
    target_min: int,
    target_max: int,
) -> list[ChunkOutput]:
    chunks: list[ChunkOutput] = []
    buf: list[str] = []
    buf_tokens = 0
    ord_ = start_ord

    def flush() -> None:
        nonlocal buf, buf_tokens, ord_
        if not buf:
            return
        text = " ".join(buf).strip()
        chunks.append(
            ChunkOutput(
                text=text,
                page=page,
                heading_path=heading,
                ord=ord_,
                token_count=buf_tokens,
            )
        )
        ord_ += 1
        buf = []
        buf_tokens = 0

    for sent in sentences:
        s_tokens = count_tokens(sent)
        if s_tokens >= target_max:
            flush()
            words = sent.split()
            current: list[str] = []
            current_tokens = 0
            for w in words:
                w_tokens = count_tokens(w + " ")
                if current_tokens + w_tokens > target_max and current:
                    chunks.append(
                        ChunkOutput(
                            text=" ".join(current),
                            page=page,
                            heading_path=heading,
                            ord=ord_,
                            token_count=current_tokens,
                        )
                    )
                    ord_ += 1
                    current = []
                    current_tokens = 0
                current.append(w)
                current_tokens += w_tokens
            if current:
                chunks.append(
                    ChunkOutput(
                        text=" ".join(current),
                        page=page,
                        heading_path=heading,
                        ord=ord_,
                        token_count=current_tokens,
                    )
                )
                ord_ += 1
            continue
        if buf_tokens + s_tokens > target_max and buf:
            flush()
        buf.append(sent)
        buf_tokens += s_tokens
        if buf_tokens >= target_min:
            pass
    flush()
    return chunks


def chunk_document(
    doc: ParsedDocument,
    *,
    target_min: int = 400,
    target_max: int = 800,
) -> list[ChunkOutput]:
    chunks: list[ChunkOutput] = []
    next_ord = 0
    for section in doc.sections:
        if not section.text or not section.text.strip():
            continue
        sentences = _split_sentences(section.text)
        section_chunks = _pack(
            sentences,
            page=section.page,
            heading=section.heading_path,
            start_ord=next_ord,
            target_min=target_min,
            target_max=target_max,
        )
        chunks.extend(section_chunks)
        next_ord = chunks[-1].ord + 1 if chunks else next_ord
    return chunks

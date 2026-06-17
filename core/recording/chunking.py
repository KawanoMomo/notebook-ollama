from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from core.recording.segment_correct import Segment


@dataclass
class RecordingChunk:
    ord: int
    text: str
    start_ms: int
    end_ms: int
    speaker: str
    token_count: int


def chunk_segments(segments: list[Segment], *, max_tokens: int,
                   token_counter: Callable[[str], int]) -> list[RecordingChunk]:
    chunks: list[RecordingChunk] = []
    buf: list[Segment] = []
    buf_tokens = 0

    def flush():
        nonlocal buf, buf_tokens
        if not buf:
            return
        text = " ".join(s.text.strip() for s in buf if s.text.strip())
        chunks.append(RecordingChunk(
            ord=len(chunks), text=text,
            start_ms=min(s.start_ms for s in buf), end_ms=max(s.end_ms for s in buf),
            speaker=buf[0].speaker, token_count=token_counter(text),
        ))
        buf = []
        buf_tokens = 0

    for seg in segments:
        t = token_counter(seg.text)
        same_speaker = bool(buf) and buf[0].speaker == seg.speaker
        if buf and (not same_speaker or buf_tokens + t > max_tokens):
            flush()
        buf.append(seg)
        buf_tokens += t
    flush()
    return chunks

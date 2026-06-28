from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_CITATION_RE = re.compile(r"\[\^(\d+)\]")


def find_citation_numbers(text: str) -> list[int]:
    seen: list[int] = []
    for m in _CITATION_RE.finditer(text):
        n = int(m.group(1))
        if n not in seen:
            seen.append(n)
    return seen


@dataclass
class CitationSpec:
    chunk_id: str
    source_id: str
    source_title: str
    location: str
    url_or_path: str | None
    snippet: str
    audio_source_id: str | None = None
    audio_start_ms: int | None = None
    audio_channel: str | None = None


def build_citations(*, answer: str, specs: dict[int, CitationSpec]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for n in find_citation_numbers(answer):
        spec = specs.get(n)
        if spec is None:
            continue
        out.append(
            {
                "n": n,
                "chunk_id": spec.chunk_id,
                "source_id": spec.source_id,
                "source_title": spec.source_title,
                "location": spec.location,
                "url_or_path": spec.url_or_path,
                "snippet": spec.snippet,
                "audio_source_id": spec.audio_source_id,
                "audio_start_ms": spec.audio_start_ms,
                "audio_channel": spec.audio_channel,
            }
        )
    return out

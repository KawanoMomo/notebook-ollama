from __future__ import annotations

from typing import Any, Protocol

from core.generation.locations import format_location
from core.retrieval.search import RetrievedChunk


class _RetrievalLike(Protocol):
    async def search(self, *, notebook_id: str, query: str, limit: int) -> list[RetrievedChunk]: ...


async def find_quotes_tool(
    *,
    notebook_id: str,
    query: str,
    max_quotes: int,
    retrieval: _RetrievalLike,
) -> dict[str, Any]:
    capped = min(max(max_quotes, 1), 10)
    hits = await retrieval.search(notebook_id=notebook_id, query=query, limit=capped)
    quotes = [
        {
            "text": h.text,
            "source_title": h.source_title,
            "location": format_location(page=h.page, heading_path=h.heading_path),
        }
        for h in hits[:capped]
    ]
    return {"quotes": quotes}

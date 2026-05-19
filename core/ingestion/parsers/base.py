from __future__ import annotations

from typing import Protocol

from core.ingestion.types import ParsedDocument


class Parser(Protocol):
    kind: str

    def parse_bytes(self, data: bytes, *, source_hint: str | None = None) -> ParsedDocument: ...

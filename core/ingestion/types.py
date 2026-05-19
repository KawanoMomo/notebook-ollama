from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParsedSection:
    text: str
    page: int | None = None
    heading_path: list[str] = field(default_factory=list)
    ord: int = 0


@dataclass
class ParsedDocument:
    title: str
    sections: list[ParsedSection] = field(default_factory=list)

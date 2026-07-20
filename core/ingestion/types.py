from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParsedSection:
    text: str
    page: int | None = None
    heading_path: list[str] = field(default_factory=list)
    ord: int = 0


@dataclass
class ParsedAsset:
    kind: str  # 'table' | 'figure'
    page: int          # 1-origin
    bbox: tuple[float, float, float, float]
    html: str | None = None
    md_snippet: str | None = None
    image_png: bytes | None = None


@dataclass
class ParsedDocument:
    title: str
    sections: list[ParsedSection] = field(default_factory=list)
    assets: list[ParsedAsset] = field(default_factory=list)

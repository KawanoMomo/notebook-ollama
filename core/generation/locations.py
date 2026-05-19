from __future__ import annotations


def format_location(*, page: int | None, heading_path: str | None) -> str:
    parts: list[str] = []
    if page is not None:
        parts.append(f"p.{page}")
    if heading_path:
        parts.append(heading_path)
    return ", ".join(parts)

from __future__ import annotations


def format_timecode(ms: int) -> str:
    total = max(0, int(ms)) // 1000
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_location(
    *,
    page: int | None,
    heading_path: str | None,
    start_ms: int | None = None,
    speaker: str | None = None,
    tile_index: int | None = None,
) -> str:
    if start_ms is not None or speaker is not None:
        parts: list[str] = []
        if speaker:
            parts.append(speaker)
        if start_ms is not None:
            parts.append(format_timecode(start_ms))
        return " ".join(parts)
    parts = []
    if page is not None:
        # tile_index は 0 始まりで保持し、表示だけ 1 始まりにする (Stage 4)
        parts.append(f"p.{page} タイル{tile_index + 1}" if tile_index is not None else f"p.{page}")
    if heading_path:
        parts.append(heading_path)
    return ", ".join(parts)

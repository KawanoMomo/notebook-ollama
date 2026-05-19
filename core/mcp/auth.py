from __future__ import annotations

import secrets
from pathlib import Path

from core.exceptions import AppError, ErrorCode


def ensure_token(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    path.write_text(token, encoding="utf-8")
    return token


def verify_token(path: Path, *, header_value: str | None) -> None:
    expected = ensure_token(path)
    if not header_value:
        raise AppError(ErrorCode.MCP_UNAUTHORIZED, "missing Authorization header")
    parts = header_value.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AppError(ErrorCode.MCP_UNAUTHORIZED, "expected Bearer token")
    if not secrets.compare_digest(parts[1], expected):
        raise AppError(ErrorCode.MCP_UNAUTHORIZED, "token mismatch")

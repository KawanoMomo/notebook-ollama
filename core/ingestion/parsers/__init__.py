from __future__ import annotations

from core.exceptions import AppError, ErrorCode
from core.ingestion.parsers.base import Parser


_REGISTRY: dict[str, Parser] = {}


def register(parser: Parser) -> None:
    _REGISTRY[parser.kind] = parser


def get_parser(kind: str) -> Parser:
    p = _REGISTRY.get(kind)
    if p is None:
        raise AppError(ErrorCode.INGESTION_UNSUPPORTED_KIND, f"no parser for kind={kind}")
    return p


def known_kinds() -> list[str]:
    return sorted(_REGISTRY.keys())

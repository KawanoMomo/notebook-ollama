from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    INPUT_INVALID = "input.invalid"
    # Prompt icon upload: payload too large (413) と unsupported media (415)
    # を AppError 体系で区別する。これにより main.py の status_map で正確な
    # HTTP ステータスへ写像できる。
    INPUT_PAYLOAD_TOO_LARGE = "input.payload_too_large"
    INPUT_UNSUPPORTED_MEDIA = "input.unsupported_media"
    INGESTION_PARSE_FAILED = "ingestion.parse_failed"
    INGESTION_FETCH_FAILED = "ingestion.fetch_failed"
    INGESTION_UNSUPPORTED_KIND = "ingestion.unsupported_kind"
    INGESTION_DUPLICATE = "ingestion.duplicate"
    INGESTION_DEP_MISSING = "ingestion.dependency_missing"
    OLLAMA_UNREACHABLE = "ollama.unreachable"
    OLLAMA_MODEL_NOT_FOUND = "ollama.model_not_found"
    OLLAMA_GENERATION_FAILED = "ollama.generation_failed"
    GENERATION_CONTEXT_OVERFLOW = "generation.context_overflow"
    RETRIEVAL_NO_RESULTS = "retrieval.no_results"
    STORAGE_NOT_FOUND = "storage.not_found"
    STORAGE_CONFLICT = "storage.conflict"
    QDRANT_UNREACHABLE = "qdrant.unreachable"
    MCP_UNAUTHORIZED = "mcp.unauthorized"


@dataclass
class AppError(Exception):
    code: ErrorCode
    message: str
    detail: str | None = None
    remediation: str | None = None

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code.value,
                "message": self.message,
                "detail": self.detail,
                "remediation": self.remediation,
            }
        }

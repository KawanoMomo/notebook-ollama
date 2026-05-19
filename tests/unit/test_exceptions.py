import pytest
from core.exceptions import AppError, ErrorCode

def test_app_error_carries_code_message_detail_remediation():
    err = AppError(
        ErrorCode.OLLAMA_UNREACHABLE,
        "Ollama に接続できません",
        detail="connection refused",
        remediation="Settings から確認してください",
    )
    assert err.code == ErrorCode.OLLAMA_UNREACHABLE
    assert err.message == "Ollama に接続できません"
    assert err.detail == "connection refused"
    assert err.remediation == "Settings から確認してください"

def test_app_error_to_dict_matches_response_schema():
    err = AppError(ErrorCode.INGESTION_PARSE_FAILED, "parse failed")
    payload = err.to_dict()
    assert payload == {
        "error": {
            "code": "ingestion.parse_failed",
            "message": "parse failed",
            "detail": None,
            "remediation": None,
        }
    }

def test_error_code_enum_uses_dotted_namespace():
    assert ErrorCode.OLLAMA_UNREACHABLE.value == "ollama.unreachable"
    assert ErrorCode.GENERATION_CONTEXT_OVERFLOW.value == "generation.context_overflow"
    assert ErrorCode.MCP_UNAUTHORIZED.value == "mcp.unauthorized"

def test_app_error_is_raisable():
    with pytest.raises(AppError) as excinfo:
        raise AppError(ErrorCode.RETRIEVAL_NO_RESULTS, "no hits")
    assert excinfo.value.code == ErrorCode.RETRIEVAL_NO_RESULTS

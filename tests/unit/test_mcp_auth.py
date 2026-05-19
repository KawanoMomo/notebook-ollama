import pytest
from core.exceptions import AppError, ErrorCode
from core.mcp.auth import ensure_token, verify_token

def test_ensure_token_creates_persistent_file(tmp_path):
    p = tmp_path / "mcp.token"
    t1 = ensure_token(p)
    assert p.exists()
    assert len(t1) >= 32
    t2 = ensure_token(p)
    assert t1 == t2  # idempotent

def test_verify_token_ok(tmp_path):
    p = tmp_path / "mcp.token"
    t = ensure_token(p)
    verify_token(p, header_value=f"Bearer {t}")

def test_verify_token_rejects_missing(tmp_path):
    p = tmp_path / "mcp.token"
    ensure_token(p)
    with pytest.raises(AppError) as exc:
        verify_token(p, header_value=None)
    assert exc.value.code == ErrorCode.MCP_UNAUTHORIZED

def test_verify_token_rejects_wrong(tmp_path):
    p = tmp_path / "mcp.token"
    ensure_token(p)
    with pytest.raises(AppError):
        verify_token(p, header_value="Bearer wrong-token")

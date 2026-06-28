"""DomainError 階層と safe_message_for ヘルパのテスト (spec §6.3)。

設計意図:
- `DomainError` は spec §6.3 「3 層防御」の中段。固定文字列 `safe_message` を
  公開可能なメッセージとして外部へ送出する。
- 既存の `AppError` 階層は **そのまま動かす** (継承させない / ALONGSIDE)。
  これは「DomainError 追加で AppError の catch サイトが壊れないこと」を
  構造的に保証するため。
- `safe_message_for(exc, origin)` は redactor とは別の高水準ヘルパで、
  fallback として `f"{type(exc).__name__} in {origin}"` を返す。発生箇所
  ヒントを残しつつ、例外本体の内容は一切埋め込まない。
"""
from __future__ import annotations

import pytest

from core.crash_reporter.domain_errors import (
    DOMAIN_ERROR_REGISTRY,
    MissingQdrantCollection,
    OllamaTimeout,
)
from core.exceptions import AppError, DomainError, ErrorCode, safe_message_for

# ----------------------------------------------------------------------------
# DomainError base
# ----------------------------------------------------------------------------


def test_domain_error_is_exception_subclass():
    assert issubclass(DomainError, Exception)


def test_domain_error_base_has_empty_safe_message():
    # ベース自身は固定文字列を持たない。サブクラスが override する契約。
    assert DomainError.safe_message == ""


def test_domain_error_subclass_init_subclass_rejects_newline_in_safe_message():
    with pytest.raises(ValueError):
        class _Bad(DomainError):
            safe_message = "first line\nleaked second line"


def test_domain_error_subclass_init_subclass_rejects_non_str_safe_message():
    with pytest.raises(TypeError):
        class _Bad(DomainError):
            safe_message = 12345  # type: ignore[assignment]


# ----------------------------------------------------------------------------
# DOMAIN_ERROR_REGISTRY parametrized contract
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cls",
    sorted(DOMAIN_ERROR_REGISTRY, key=lambda c: c.__name__),
    ids=lambda c: c.__name__,
)
def test_every_registered_domain_error_has_nonempty_safe_message(cls):
    assert issubclass(cls, DomainError)
    assert isinstance(cls.safe_message, str)
    assert cls.safe_message != ""
    # 公開メッセージは 1 行・短く・PII を含めない契約 (spec §6.3)。
    assert "\n" not in cls.safe_message
    assert "\r" not in cls.safe_message
    assert len(cls.safe_message) <= 120


@pytest.mark.parametrize(
    "cls",
    sorted(DOMAIN_ERROR_REGISTRY, key=lambda c: c.__name__),
    ids=lambda c: c.__name__,
)
def test_every_registered_domain_error_is_raisable(cls):
    with pytest.raises(cls):
        raise cls("internal payload")
    # DomainError でも catch できる
    with pytest.raises(DomainError):
        raise cls("internal payload")


# ----------------------------------------------------------------------------
# Concrete subclasses sanity
# ----------------------------------------------------------------------------


def test_missing_qdrant_collection_safe_message():
    assert MissingQdrantCollection.safe_message == "Qdrant collection not found"


def test_ollama_timeout_safe_message():
    assert OllamaTimeout.safe_message == "Ollama request timed out"


# ----------------------------------------------------------------------------
# safe_message_for routing
# ----------------------------------------------------------------------------


def test_safe_message_for_returns_safe_message_for_domain_error():
    err = MissingQdrantCollection("internal qdrant detail with doc_id=abc")
    assert safe_message_for(err, origin="rag.search") == "Qdrant collection not found"


def test_safe_message_for_falls_back_to_type_and_origin_for_unknown():
    err = ValueError("doc_id=abc was missing — leak!")
    msg = safe_message_for(err, origin="rag.search")
    assert msg == "ValueError in rag.search"
    # 例外本体は絶対に埋め込まない
    assert "doc_id" not in msg
    assert "abc" not in msg
    assert "leak" not in msg


def test_safe_message_for_default_origin_is_unknown_marker():
    msg = safe_message_for(RuntimeError("x"))
    assert msg == "RuntimeError in <unknown>"


def test_safe_message_for_with_empty_safe_message_falls_back():
    """safe_message を空のまま継承したサブクラスは fallback されること。

    これにより「safe_message を設定し忘れた」サブクラスでも、内部メッセージが
    漏れることはない (空文字 → fallback 経路へ)。
    """
    class _Forgotten(DomainError):
        pass  # safe_message を override し忘れた

    err = _Forgotten("internal that must not leak")
    msg = safe_message_for(err, origin="some.module")
    assert msg == "_Forgotten in some.module"
    assert "internal" not in msg
    assert "leak" not in msg


def test_safe_message_for_with_app_error_falls_back_to_type_name():
    err = AppError(ErrorCode.STORAGE_NOT_FOUND, "internal storage detail")
    msg = safe_message_for(err, origin="storage.fetch")
    assert msg == "AppError in storage.fetch"
    assert "internal" not in msg


# ----------------------------------------------------------------------------
# Backward compatibility: existing AppError catch sites must still work
# ----------------------------------------------------------------------------


def test_app_error_still_raisable_and_catchable_as_app_error():
    """Smoke test: 既存 AppError の except 経路を壊していないこと。"""
    with pytest.raises(AppError) as excinfo:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "x")
    assert excinfo.value.code == ErrorCode.STORAGE_NOT_FOUND
    assert excinfo.value.message == "x"


def test_app_error_is_not_a_domain_error_subclass():
    """ALONGSIDE 配置: AppError は DomainError を継承しない。

    継承させてしまうと、誰かが `except DomainError:` で AppError まで掴んで
    しまい既存挙動が変わる。意図的に独立階層とする。
    """
    err = AppError(ErrorCode.OLLAMA_UNREACHABLE, "x")
    assert not isinstance(err, DomainError)
    assert not issubclass(AppError, DomainError)


def test_app_error_to_dict_unchanged():
    """既存 schema 互換: to_dict の形が変わっていないこと。"""
    err = AppError(ErrorCode.INGESTION_PARSE_FAILED, "parse failed")
    assert err.to_dict() == {
        "error": {
            "code": "ingestion.parse_failed",
            "message": "parse failed",
            "detail": None,
            "remediation": None,
        }
    }

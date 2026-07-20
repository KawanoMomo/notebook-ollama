from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar


class ErrorCode(StrEnum):
    INPUT_INVALID = "input.invalid"
    DEV_UNAUTHORIZED = "dev.unauthorized"
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


# ---------------------------------------------------------------------------
# DomainError 階層 (spec §6.3 — クラッシュレポートの「3 層防御」中段)
# ---------------------------------------------------------------------------
#
# 設計意図:
# - `AppError` は HTTP ステータス写像 / フロント i18n キー解決に使う構造化エラ
#   ーで、`message` フィールドにはユーザー向け説明文 (例外発生時の文脈) が
#   入る。これはユーザー入力や RAG ドキュメント由来の文字列を含みうる。
# - 一方クラッシュレポート (=外部公開される GitHub Issue 本文) には、
#   「事前に開発者が承認した固定文字列」しか流したくない。そのために
#   `DomainError.safe_message: ClassVar[str]` を新設する。
# - `AppError` は **意図的に DomainError を継承させない** (ALONGSIDE)。
#   継承させると `except DomainError:` が AppError まで掴んでしまい、
#   既存ハンドラの挙動を変えてしまう。階層を独立に保つことで、新階層追加
#   による既存 catch サイトの破壊を構造的に防ぐ。
# - 想定外の例外 (DomainError も AppError も継承していない) に対しては
#   `safe_message_for()` が `f"{type(exc).__name__} in {origin}"` を返す。
#   例外本文 (`str(exc)`) は一切埋め込まないため、内部ペイロードリークを
#   起こさない。


class DomainError(Exception):
    """ドメイン固有例外の基底。サブクラスは固定文字列 ``safe_message`` を持つ。

    ``safe_message`` は **外部公開しても安全な短い説明文** (英語推奨、改行不可、
    120 字以内)。クラッシュレポート本文 / フロント通知などで使用する。

    Notes:
        サブクラス定義時に ``__init_subclass__`` で形式 (型 / 改行 / 長さ) を
        検証する。これにより、巨大な内部状態や複数行のスタックトレースを
        うっかり ``safe_message`` に貼り付けるミスを早期に潰す。
    """

    safe_message: ClassVar[str] = ""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # 直接 cls.__dict__ を見ることで、親から継承しただけのサブクラスは
        # 検証対象外とする (継承だけしてさらにサブクラス化するパターンを許容)。
        sm = cls.__dict__.get("safe_message")
        if sm is None:
            return  # この class では override していない → スキップ
        if not isinstance(sm, str):
            raise TypeError(
                f"{cls.__name__}.safe_message must be str, "
                f"got {type(sm).__name__}"
            )
        # 改行・タブ・キャリッジリターンは禁止 (Issue 本文 / ヘッダで崩れる)
        if any(ch in sm for ch in ("\n", "\r", "\t")):
            raise ValueError(
                f"{cls.__name__}.safe_message must not contain control "
                f"characters (newline / tab)"
            )
        if len(sm) > 120:
            raise ValueError(
                f"{cls.__name__}.safe_message too long "
                f"({len(sm)} > 120 chars)"
            )


def safe_message_for(exc: BaseException, origin: str = "<unknown>") -> str:
    """例外を外部公開可能な短い文字列に変換する (spec §6.3)。

    Routing:
        - ``DomainError`` インスタンスで ``safe_message`` が空でない場合
          → ``safe_message`` をそのまま返す。
        - それ以外 (``AppError`` 含む / 想定外例外含む / safe_message が
          空のサブクラス含む) → ``f"{type(exc).__name__} in {origin}"``。

    Args:
        exc: 検疫対象の例外。
        origin: 例外発生箇所を示すヒント文字列 (例: ``"rag.search"``)。
            fallback 経路でのみ使う。クラッシュレポートでは関数名 /
            モジュール名 / ルータパス pattern などを呼び出し側で渡す。

    Returns:
        外部公開しても安全な 1 行文字列。
    """
    if isinstance(exc, DomainError) and exc.safe_message:
        return exc.safe_message
    return f"{type(exc).__name__} in {origin}"

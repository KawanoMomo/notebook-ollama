"""クラッシュレポート用 DomainError のサンプル定義 (spec §6.3)。

このモジュールは「外部公開しても安全な固定 ``safe_message`` を持つ例外」を
集約する。クラッシュレポート機能が body に埋め込んでよい唯一のメッセージは
ここに登録された ``DomainError`` の ``safe_message`` だけ (それ以外は
:func:`core.exceptions.safe_message_for` の fallback で型名 + 発生箇所のみが
出る)。

Migration note:
    spec §15 で「既存例外の DomainError 移行は機能追加時に随時」と決めて
    いるため、本モジュールは Sprint 3 では代表 2 種類のみを置く。
    新規 DomainError を追加する場合は必ず ``DOMAIN_ERROR_REGISTRY`` にも
    登録し、テスト ``test_every_registered_domain_error_*`` が自動的に
    新サブクラスを検証する形にする (ハンドロール禁止)。
"""
from __future__ import annotations

from core.exceptions import DomainError


class MissingQdrantCollection(DomainError):
    """Qdrant のターゲットコレクションが存在しない時に投げる。

    例: 初回起動直後にユーザーが検索したが、まだ ingest 済みドキュメントが
    無く collection が未作成だった場合など。
    """

    safe_message = "Qdrant collection not found"


class OllamaTimeout(DomainError):
    """Ollama サーバへのリクエストが既定タイムアウトを超えた時に投げる。

    例: 巨大プロンプトで生成が長引き、httpx の read timeout を超過した場合。
    """

    safe_message = "Ollama request timed out"


# ---------------------------------------------------------------------------
# Registry — テスト側はこのタプルを iterate して全 DomainError を検証する。
# 新規 DomainError を追加した際は **必ずここに追記** する (適応漏れ防止)。
# ---------------------------------------------------------------------------
DOMAIN_ERROR_REGISTRY: tuple[type[DomainError], ...] = (
    MissingQdrantCollection,
    OllamaTimeout,
)

__all__ = [
    "DOMAIN_ERROR_REGISTRY",
    "MissingQdrantCollection",
    "OllamaTimeout",
]

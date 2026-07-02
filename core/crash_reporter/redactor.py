"""ホワイトリスト方式の構造化ログ / トレースバック / 例外メッセージ検疫。

spec §6.2 / §6.3 準拠。"通す"フィールドだけを通し、ブラックリスト fallback は
しない。これによりログスキーマ追加時のリーク事故を構造的に防ぐ。
"""
from __future__ import annotations

from pathlib import Path

from core.crash_reporter import BLOCKED_LOG_KEYS

ALLOWED_LOG_FIELDS: frozenset[str] = frozenset({
    "level", "event_name", "timestamp", "request_id",
    "method", "path_pattern", "status_code", "duration_ms",
    "exception_type", "exception_module", "error_kind",
    "count", "n_chunks", "n_sources", "top_k",
    "model",
})
"""spec §6.2「通す」フィールドのホワイトリスト。これ以外は構造化ログから除外。"""


def _has_blocked_key_recursive(value: object) -> bool:
    """value (dict / list / scalar) の中に禁止キーが 1 つでも含まれるか。

    トップレベルしか見ない実装だと、たとえば
    ``{"level": "INFO", "model": {"chunk_text": "leaked"}}`` のように
    ホワイトリストキー (``model``) の値に禁止キーがネストされていると
    検出できず PII が漏れる。本関数は dict 値 / list 要素を再帰的にたどり、
    どこかに禁止キーがあれば True を返す。
    """
    if isinstance(value, dict):
        for k, v in value.items():
            if k in BLOCKED_LOG_KEYS:
                return True
            if _has_blocked_key_recursive(v):
                return True
        return False
    if isinstance(value, list | tuple):
        return any(_has_blocked_key_recursive(item) for item in value)
    return False


def redact_log_event(event: dict) -> dict | None:
    """構造化ログ 1 イベントを検疫する。

    - 禁止キーが 1 つでも (任意の深さで) 含まれれば ``None`` を返す (行ごと破棄)。
    - 残りはホワイトリスト ``ALLOWED_LOG_FIELDS`` のキーだけを残す。
    """
    if _has_blocked_key_recursive(event):
        return None
    return {k: v for k, v in event.items() if k in ALLOWED_LOG_FIELDS}


def _normalize_path_separators(s: str) -> str:
    """Path 文字列の区切り文字をすべて ``/`` に正規化する。

    Windows traceback では同一パスが ``C:\\Users\\momo`` でも
    ``C:/Users/momo`` でも現れうるため、HOME 一致判定の前に正規化する。
    """
    return s.replace("\\", "/")


def redact_traceback(tb_lines: list[str], app_root: Path) -> list[str]:
    """traceback 各行から個人識別パスを除去する。

    - HOME 配下のパスを ``<HOME>/...`` に置換 (Windows ``\\`` / POSIX ``/`` 両対応)。
    - ``app_root`` 配下の行はそのまま残す (spec §6.2: アプリパッケージは debug 用に保持)。
    - ``site-packages/`` 配下はそのまま残す (HOME 文字列を含まないので素通り)。
    """
    home_str = _normalize_path_separators(str(Path.home()))
    app_root_str = _normalize_path_separators(str(app_root))
    # ``Path("")`` becomes ``"."`` — treat that as "no HOME", otherwise we would
    # replace every ``.`` in the line (filenames, version numbers, …) with
    # ``<HOME>``. ``"/"`` would have the same pathological behaviour.
    _MEANINGLESS_HOMES = {"", ".", "/"}
    out: list[str] = []
    for line in tb_lines:
        normalized = _normalize_path_separators(line)
        # app_root 配下はそのまま (spec §6.2 「app_root配下はそのまま残す」)
        if app_root_str and app_root_str not in _MEANINGLESS_HOMES \
                and app_root_str in normalized:
            out.append(line)
            continue
        if home_str not in _MEANINGLESS_HOMES and home_str in normalized:
            out.append(normalized.replace(home_str, "<HOME>"))
            continue
        out.append(line)
    return out


def redact_exception_message(exc: BaseException) -> str:
    """spec §6.3 3 層防御。DomainError なら safe_message、未知例外は型名のみ。"""
    safe = getattr(exc, "safe_message", None)
    if isinstance(safe, str) and safe:
        return safe
    cls = type(exc)
    return f"{cls.__module__}.{cls.__qualname__}"

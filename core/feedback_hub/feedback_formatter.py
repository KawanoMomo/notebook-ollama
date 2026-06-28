"""ご意見・ご要望の GitHub Issue 起票 URL ビルダー。

spec §5.5 / §7.1 (POST /api/feedback-hub/feedback) — Sprint 3 Task 3.7。

設計方針:

- ``build_feedback_issue_url`` は GitHub Issue prefill URL を 1 本の str で返す
  純粋関数。タイトル / Markdown body / labels を組み立て、URL 長が
  ``MAX_URL_LEN`` を超えないことを保証する。
- 入力 (``kind`` / ``sentiment`` / ``body``) は **境界で** ``ValueError`` を投げ、
  禁止文字やレジストリ外の値が「サイレントに通る」事故を防ぐ。Pydantic 層と
  二重防衛になるが、formatter 単体でも安全に呼べることを優先する。
- 8KB 制限のため、`prefill_url.build_issue_url` の log-section trimming は
  ログ Markdown 構造に密結合しており feedback body には使えない。代わりに
  body を末尾から二分探索で短くする (``_safe_build_url``)。
- ``screenshot_url`` (任意) は body 末尾に Markdown 画像参照として埋め込む。
  ``screenshot_b64`` 等の生バイナリは URL に乗らない (8KB 制限) ため、
  ホストされた URL のみを受け付ける。
"""
from __future__ import annotations

from typing import Literal
from urllib.parse import quote_plus, urlencode

from core.crash_reporter import MAX_URL_LEN, REPO_SLUG

Kind = Literal["feature", "complaint", "impression"]
Sentiment = Literal["up", "neutral", "down"]

VALID_KINDS: frozenset[str] = frozenset({"feature", "complaint", "impression"})
"""旗ハブ「ご意見」タブの 3 チップに対応する種別レジストリ。"""

VALID_SENTIMENTS: frozenset[str] = frozenset({"up", "neutral", "down"})
"""Thumbs 3 段階 (上/中立/下) の感情入力レジストリ。"""

_KIND_LABEL_JP: dict[str, str] = {
    "feature": "機能要望",
    "complaint": "使いにくさ",
    "impression": "感想",
}
"""body Markdown / title に出す日本語表記。"""

_SENTIMENT_GLYPH_JP: dict[str, str] = {
    "up": "👍 up",
    "neutral": "─ neutral",
    "down": "👎 down",
}

_TITLE_PREFIX = "[feedback] "
_TITLE_MAX = 80
_TRUNCATE_MARKER = "\n\n... (本文が URL 制限を超えたため自動で切り詰めました)"


def _check_str(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string, got {type(value).__name__}")
    return value


def _validate_kind(kind: object) -> str:
    k = _check_str("kind", kind)
    if k not in VALID_KINDS:
        raise ValueError(
            f"invalid kind: {k!r} (expected one of {sorted(VALID_KINDS)})"
        )
    return k


def _validate_sentiment(sentiment: object) -> str | None:
    if sentiment is None:
        return None
    s = _check_str("sentiment", sentiment)
    if s not in VALID_SENTIMENTS:
        raise ValueError(
            f"invalid sentiment: {s!r} "
            f"(expected one of {sorted(VALID_SENTIMENTS)} or None)"
        )
    return s


def _validate_body(body: object) -> str:
    b = _check_str("body", body)
    if not b.strip():
        raise ValueError("body must not be empty / whitespace-only")
    return b


def _build_title(kind: str, body: str) -> str:
    """``[feedback] (機能要望) <body 先頭行>`` 形式のタイトル。

    Unicode code point 数で `_TITLE_MAX` 以内に収める。末尾が
    切れる場合は ``…`` で置換する。
    """
    first_line = next(
        (line.strip() for line in body.splitlines() if line.strip()), ""
    )
    raw = f"{_TITLE_PREFIX}({_KIND_LABEL_JP[kind]}) {first_line}"
    if len(raw) <= _TITLE_MAX:
        return raw
    return raw[: _TITLE_MAX - 1] + "…"


def _build_body(
    kind: str, body: str, sentiment: str | None, screenshot_url: str | None
) -> str:
    """Issue 本文 Markdown を組み立てる。

    構成:
    - ``## ご意見・ご要望`` 見出し + 本文 (ユーザー入力をそのまま)
    - ``---`` フッタに種別 / 感情 / (任意) スクショ URL を Markdown 画像参照で埋め込む
    """
    lines: list[str] = [
        "## ご意見・ご要望",
        "",
        body.strip(),
        "",
        "---",
        f"- 種別: {_KIND_LABEL_JP[kind]} (`{kind}`)",
    ]
    if sentiment is not None:
        lines.append(f"- 感情: {_SENTIMENT_GLYPH_JP[sentiment]} (`{sentiment}`)")
    else:
        lines.append("- 感情: (未回答)")
    if screenshot_url:
        # Markdown 画像参照 — GitHub Issue 上で URL から直接プレビューされる。
        lines.append("")
        lines.append(f"![screenshot]({screenshot_url})")
    return "\n".join(lines) + "\n"


def _build_url(title: str, body: str, labels: list[str], repo: str) -> str:
    base = f"https://github.com/{repo}/issues/new"
    params = {
        "title": title,
        "body": body,
        "labels": ",".join(labels),
    }
    return f"{base}?{urlencode(params, quote_via=quote_plus)}"


def _safe_build_url(
    title: str, body: str, labels: list[str], repo: str
) -> str:
    """URL が ``MAX_URL_LEN`` 以内になるよう body を二分探索で切り詰める。

    Title / labels は常に保持する (検索性のため落とせない)。body は末尾から
    削り、削れた印として ``_TRUNCATE_MARKER`` を末尾に付ける。
    どうしても入らない場合 (タイトル/labels だけで既に超過) はマーカーだけの
    最小 body を返す (実装ガードレール — 通常の入力では発生しない)。
    """
    url = _build_url(title, body, labels, repo)
    if len(url) <= MAX_URL_LEN:
        return url

    # 二分探索: body を [0:mid] に切り詰めて URL 長を測る。
    lo, hi = 0, len(body)
    best: str | None = None
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate_body = body[:mid].rstrip() + _TRUNCATE_MARKER
        candidate_url = _build_url(title, candidate_body, labels, repo)
        if len(candidate_url) <= MAX_URL_LEN:
            best = candidate_url
            lo = mid + 1
        else:
            hi = mid - 1
    if best is not None:
        return best
    # title / labels だけで超過するケース (理論上のみ): body をマーカーだけにする。
    return _build_url(title, _TRUNCATE_MARKER.lstrip(), labels, repo)


def build_feedback_issue_url(
    *,
    kind: str,
    body: str,
    sentiment: str | None,
    screenshot_url: str | None = None,
    repo: str = REPO_SLUG,
) -> str:
    """GitHub Issue 起票 URL を返す。

    Args:
        kind: ``VALID_KINDS`` のいずれか。
        body: ご意見本文。空 / whitespace-only は不可。
        sentiment: ``VALID_SENTIMENTS`` のいずれか、または ``None`` (未回答)。
        screenshot_url: 公開アクセス可能なスクショ URL。あれば body 末尾に
            Markdown 画像参照として埋め込む。
        repo: 起票先リポジトリ slug (デフォルト ``REPO_SLUG``)。

    Returns:
        ``https://github.com/<repo>/issues/new?title=...&body=...&labels=...``
        の形の URL。``len(url) <= MAX_URL_LEN`` を保証する。

    Raises:
        ValueError: 入力レジストリ外、または body が空。
    """
    k = _validate_kind(kind)
    s = _validate_sentiment(sentiment)
    b = _validate_body(body)

    title = _build_title(k, b)
    markdown = _build_body(k, b, s, screenshot_url)
    labels = ["feedback", k]
    return _safe_build_url(title, markdown, labels, repo)

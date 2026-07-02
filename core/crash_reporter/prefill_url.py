"""GitHub Issue 起票 URL ビルダー (8KB 制限対応)。

spec §10 のアルゴリズム:

1. title / body / labels をクエリパラメータに展開した URL を構築。
2. ``len(url) <= MAX_URL_LEN`` ならそのまま返す (``truncated=False``)。
3. 超えていれば body の「直近ログ」セクションを `TRIM_LINE_LEVELS` の
   順に末尾 N 行だけ残して切り詰めて再構築。収まり次第 ``truncated=True`` で返す。
4. それでも収まらなければログセクション全体を ``FALLBACK_MARKER``
   (ローカルファイル添付案内) に置換して返す。

title / labels は **常に** 保持する。ログ以外のセクション
(概要 / 環境 / スタックトレース / フッタ) も保持する。
"""
from __future__ import annotations

from urllib.parse import quote_plus, urlencode

from core.crash_reporter import MAX_URL_LEN, REPO_SLUG

LOG_SECTION_HEADER: str = "## 直近ログ (検疫済み)"
"""formatter.build_issue_body が出す Markdown 見出しと一致させること。"""

_FENCE_OPEN: str = "```jsonl"
_FENCE_CLOSE: str = "```"

TRIM_LINE_LEVELS: tuple[int, ...] = (50, 30, 20, 10)
"""spec §10 で定められた段階的切詰めレベル (降順)。"""

FALLBACK_MARKER: str = (
    "ログが長すぎてURLに収まりませんでした。"
    "ローカルファイル `<crash_id>.log` をこのIssueにドラッグ&ドロップしてください。"
)
"""最終手段: ログセクション全体をこの文字列に置換する。"""


def _find_log_block(body: str) -> tuple[int, int] | None:
    """``## 直近ログ`` ヘッダ配下の fenced block 内側 (start, end) を返す。

    fenced block の中身だけを対象にし、開始/終了フェンス自体は残す。
    ヘッダまたはフェンスが見つからなければ ``None``。
    """
    header_idx = body.find(LOG_SECTION_HEADER)
    if header_idx == -1:
        return None
    fence_open = body.find(_FENCE_OPEN, header_idx)
    if fence_open == -1:
        return None
    content_start = fence_open + len(_FENCE_OPEN)
    # 開始フェンス直後の改行はコンテンツに含めない
    if content_start < len(body) and body[content_start] == "\n":
        content_start += 1
    fence_close = body.find(_FENCE_CLOSE, content_start)
    if fence_close == -1:
        return None
    return content_start, fence_close


def _trim_log_section(body: str, n_lines: int) -> str:
    """ログセクションを末尾 ``n_lines`` 行だけ残す形に切り詰める。

    対象セクションが無い、もしくは既に ``n_lines`` 以下なら何もしない。
    """
    pos = _find_log_block(body)
    if pos is None:
        return body
    start, end = pos
    content = body[start:end]
    lines = content.splitlines(keepends=True)
    if len(lines) <= n_lines:
        return body
    kept = "".join(lines[-n_lines:])
    return body[:start] + kept + body[end:]


def _replace_log_section(body: str, marker: str) -> str:
    """ログセクション中身を ``marker`` 一行に置換する。フェンスはそのまま残す。"""
    pos = _find_log_block(body)
    if pos is None:
        return body
    start, end = pos
    return body[:start] + marker + "\n" + body[end:]


def build_issue_url(
    *,
    title: str,
    body: str,
    labels: list[str],
    repo: str = REPO_SLUG,
) -> tuple[str, bool]:
    """spec §10 に従い GitHub Issue 起票 URL を返す。

    Returns:
        (url, truncated): ``truncated`` は body のログセクションが切り詰めまたは
        マーカー置換されたかを示すフラグ。title / labels は常に保持される。
    """
    base = f"https://github.com/{repo}/issues/new"

    def _build(b: str) -> str:
        params = {
            "title": title,
            "body": b,
            "labels": ",".join(labels),
        }
        return f"{base}?{urlencode(params, quote_via=quote_plus)}"

    url = _build(body)
    if len(url) <= MAX_URL_LEN:
        return url, False

    for n in TRIM_LINE_LEVELS:
        trimmed = _trim_log_section(body, n)
        candidate = _build(trimmed)
        if len(candidate) <= MAX_URL_LEN:
            return candidate, True

    final_body = _replace_log_section(body, FALLBACK_MARKER)
    return _build(final_body), True

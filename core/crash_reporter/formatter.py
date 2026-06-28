"""GitHub Issue 起票用の Markdown body / title / labels を組み立てる純粋関数群。

spec §7.2 / §10 準拠。pending crash dict (Task 2.1 `PendingCrash` の
`dataclasses.asdict` 戻り値互換) を入力に取り、人間が読める Markdown
を返す。FastAPI / DB / I/O に触れない。

設計メモ:
- 入力は **dict** を受け取る。`pending_store.PendingCrash` dataclass と
  並行実装するため、型依存を避ける。
- code fence injection 対策: traceback / log_tail 内に ``` を含む場合、
  生 ``` を使うと fence が途中で閉じて以降の Markdown が崩れる。
  実装は「内容の中の最長 backtick 連続長 + 1」のフェンスを使う
  (CommonMark 仕様 §4.5)。
- 環境セクションは hardware.collect() の生 dict 文字列ではなく、
  人間が読みやすい行頭ラベル形式に整形する。欠落キーは
  "<unavailable>" を補う。
- "送信される/されない" 等の文言は body に含めない (UI 側でも禁止、
  [[feedback-no-data-guarantee-in-ui]])。
"""
from __future__ import annotations

import json
from typing import Any

# Issue title の最大長 (UI / 検索性のため安全マージン)。GitHub の
# title hard limit は 256 chars だが、80 で揃えることで通知一覧でも
# truncation されない短さを保つ。
_TITLE_MAX = 80

_TITLE_PREFIX = "[crash] "

_DEFAULT_LABELS: tuple[str, ...] = ("crash-auto", "needs-triage")

_HW_FIELDS = (
    "cpu_model", "cpu_cores", "cpu_threads",
    "ram_total_gb", "ram_available_gb",
    "gpu_model", "gpu_vram_mb", "driver_version",
    "os_arch", "os_platform", "python_version", "disk_free_gb",
)

_UNAVAIL = "<unavailable>"


def _hw_get(hw: dict[str, Any], key: str) -> Any:
    """hardware dict から値を取り出す。欠落時は '<unavailable>'。"""
    return hw.get(key, _UNAVAIL)


def _safe_fence(content: str, base_char: str = "`") -> str:
    """CommonMark 準拠の安全なフェンス文字列を返す。

    内容内の最長 `` ` `` 連続長より 1 つ長いフェンス (最低 3) を作る。
    これにより内容に ``` が含まれていてもパーサが内部で fence を閉じない。
    """
    max_run = 0
    cur = 0
    for ch in content:
        if ch == base_char:
            cur += 1
            if cur > max_run:
                max_run = cur
        else:
            cur = 0
    return base_char * max(3, max_run + 1)


def _code_block(content: str, lang: str = "") -> str:
    """言語タグ付き fenced code block を返す。

    末尾改行を 1 つに正規化し、安全フェンスで包む。
    """
    body = content.rstrip("\n")
    fence = _safe_fence(body)
    return f"{fence}{lang}\n{body}\n{fence}"


def _format_env_section(hw: dict[str, Any]) -> str:
    """環境セクションを人間が読める行頭ラベル形式で組み立てる。

    生 dict を貼らない (Issue を人間がレビューするので)。
    """
    cpu_model = _hw_get(hw, "cpu_model")
    cpu_cores = _hw_get(hw, "cpu_cores")
    cpu_threads = _hw_get(hw, "cpu_threads")
    ram_avail = _hw_get(hw, "ram_available_gb")
    ram_total = _hw_get(hw, "ram_total_gb")
    gpu_model = _hw_get(hw, "gpu_model")
    gpu_vram = _hw_get(hw, "gpu_vram_mb")
    drv = _hw_get(hw, "driver_version")
    os_plat = _hw_get(hw, "os_platform")
    os_arch = _hw_get(hw, "os_arch")
    py = _hw_get(hw, "python_version")
    disk = _hw_get(hw, "disk_free_gb")

    return (
        f"- CPU: {cpu_model} ({cpu_cores} cores / {cpu_threads} threads)\n"
        f"- RAM: {ram_avail} / {ram_total} GB\n"
        f"- GPU: {gpu_model} ({gpu_vram} MB, driver {drv})\n"
        f"- OS: {os_plat} ({os_arch})\n"
        f"- Python: {py}\n"
        f"- Disk free: {disk} GB"
    )


def _format_trace_block(trace: list[str]) -> str:
    """traceback 行リストを fenced code block にまとめる (言語タグなし)。"""
    content = "\n".join(trace)
    return _code_block(content, lang="")


def _format_log_tail_block(log_tail: list[dict[str, Any]]) -> str:
    """log_tail を 1 行 1 JSON の jsonl fenced block にまとめる。"""
    if not log_tail:
        content = ""
    else:
        content = "\n".join(
            json.dumps(ev, ensure_ascii=False) for ev in log_tail
        )
    return _code_block(content, lang="jsonl")


def build_issue_body(crash: dict[str, Any]) -> str:
    """pending crash dict から GitHub Issue Markdown body を組み立てる。

    入力 dict のキー (Task 2.1 `PendingCrash` 互換):
      id, fingerprint, created_at, exception_type, exception_message,
      trace (list[str]), hardware (dict), log_tail (list[dict]), source.
    """
    exc_type = crash.get("exception_type", "Unknown")
    exc_msg = crash.get("exception_message", "")
    trace = list(crash.get("trace", []))
    hw = dict(crash.get("hardware", {}))
    log_tail = list(crash.get("log_tail", []))
    crash_id = crash.get("id", "")
    fingerprint = crash.get("fingerprint", "")
    source = crash.get("source", "")

    summary = f"## 概要\n{exc_type}: {exc_msg}"
    env = f"## 環境\n{_format_env_section(hw)}"
    trace_section = f"## スタックトレース\n{_format_trace_block(trace)}"
    log_section = f"## 直近ログ (検疫済み)\n{_format_log_tail_block(log_tail)}"
    trailer = (
        "---\n"
        f"- crash_id: {crash_id}\n"
        f"- fingerprint: {fingerprint}\n"
        f"- source: {source}"
    )

    return "\n\n".join([summary, env, trace_section, log_section, trailer]) + "\n"


def build_issue_title(crash: dict[str, Any]) -> str:
    """`[crash] <exception_type>: <message>` 形式の title。

    Unicode code point 数で `_TITLE_MAX` 以内に収まるよう必要に応じて
    末尾を ellipsis (`…`) に置き換える。
    """
    exc_type = crash.get("exception_type", "Unknown")
    msg = crash.get("exception_message", "")
    # msg が空のとき末尾 ": " が残らないよう分岐する。
    raw = f"{_TITLE_PREFIX}{exc_type}: {msg}" if msg else f"{_TITLE_PREFIX}{exc_type}"
    if len(raw) <= _TITLE_MAX:
        return raw
    # ellipsis (1 文字) を含めて _TITLE_MAX に収める。
    return raw[: _TITLE_MAX - 1] + "…"


def default_labels(crash: dict[str, Any]) -> list[str]:
    """すべての crash で付ける既定ラベル。

    現状は spec §10 の `crash-auto`, `needs-triage` 固定。`crash` 引数は
    将来的に source 別ラベル (`source-fastapi` 等) を派生させる拡張点として
    シグネチャに残す (Sprint 2 では未使用、Sprint 3+ で活用予定)。
    """
    _ = crash  # 拡張点 (Sprint 3+ で source 別ラベル等に派生予定)
    return list(_DEFAULT_LABELS)

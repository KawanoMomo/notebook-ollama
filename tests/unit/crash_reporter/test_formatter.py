"""Task 2.3 — `core/crash_reporter/formatter.py` のテスト。

spec §7.2 / §10 準拠: GitHub Issue 起票用の Markdown body / title /
default labels を pending report dict から組み立てる。formatter は純粋
関数 (I/O / FastAPI 非依存)。

入力は **dict** で受け取る (Task 2.1 `PendingCrash` dataclass と
並行実装する都合上、formatter は dataclass に依存せず dict ベースで
動作する。dataclasses.asdict() の戻り値と互換)。
"""
from __future__ import annotations

import json

import pytest

from core.crash_reporter.formatter import (
    build_issue_body,
    build_issue_title,
    default_labels,
)

# ---------- fixtures -----------------------------------------------------


def _hw() -> dict[str, str | int | float]:
    """hardware.collect() 互換のサンプル dict (3 列 nvidia-smi shape)。"""
    return {
        "cpu_model": "Intel(R) Core(TM) i9-12900KF",
        "cpu_cores": 16,
        "cpu_threads": 24,
        "ram_total_gb": 31.8,
        "ram_available_gb": 18.2,
        "gpu_model": "NVIDIA GeForce RTX 2080 Ti",
        "gpu_vram_mb": 11264,
        "driver_version": "555.42",
        "os_arch": "AMD64",
        "os_platform": "Windows-11-10.0.26200-SP0",
        "python_version": "3.12.4",
        "disk_free_gb": 412.6,
    }


def _crash(**overrides) -> dict:
    """最小の pending crash dict。テストで部分上書きできる。"""
    base = {
        "id": "20260628T120000-abc12345",
        "fingerprint": "0123456789abcdef0123456789abcdef01234567",
        "created_at": "2026-06-28T12:00:00Z",
        "exception_type": "RuntimeError",
        "exception_message": "something exploded",
        "trace": [
            '  File "apps/api/main.py", line 42, in startup',
            "    raise RuntimeError('something exploded')",
            "RuntimeError: something exploded",
        ],
        "hardware": _hw(),
        "log_tail": [
            {"level": "INFO", "event_name": "boot", "timestamp": "2026-06-28T12:00:00Z"},
            {"level": "ERROR", "event_name": "rag.search", "status_code": 500},
        ],
        "source": "fastapi",
    }
    base.update(overrides)
    return base


# ---------- build_issue_body: section structure --------------------------


def test_body_has_required_sections():
    body = build_issue_body(_crash())
    assert "## 概要" in body
    assert "## 環境" in body
    assert "## スタックトレース" in body
    assert "## 直近ログ" in body  # "(検疫済み)" は実装で付くが本テストは見出しのみ


def test_body_section_order_is_summary_env_trace_log():
    body = build_issue_body(_crash())
    i_summary = body.index("## 概要")
    i_env = body.index("## 環境")
    i_trace = body.index("## スタックトレース")
    i_log = body.index("## 直近ログ")
    assert i_summary < i_env < i_trace < i_log


def test_body_summary_contains_exception_type_and_message():
    body = build_issue_body(_crash(exception_type="ValueError", exception_message="bad input"))
    # 概要セクションに型とメッセージが現れる
    summary_block = body.split("## 環境")[0]
    assert "ValueError" in summary_block
    assert "bad input" in summary_block


# ---------- build_issue_body: trailer (crash_id / fingerprint / source) ----


def test_body_trailer_includes_crash_id():
    crash = _crash(id="my-unique-crash-id")
    body = build_issue_body(crash)
    assert "my-unique-crash-id" in body
    # trailer は body の末尾セクションにある
    assert body.rindex("my-unique-crash-id") > body.index("## 直近ログ")


def test_body_trailer_includes_fingerprint():
    crash = _crash(fingerprint="deadbeef" * 5)
    body = build_issue_body(crash)
    assert ("deadbeef" * 5) in body
    assert body.rindex("deadbeef" * 5) > body.index("## 直近ログ")


@pytest.mark.parametrize(
    "source",
    sorted({"fastapi", "excepthook", "signal", "atexit", "frontend", "unclean_shutdown"}),
)
def test_body_trailer_includes_every_valid_source(source):
    """spec の全 source enum 値が trailer に流れることを網羅確認。"""
    body = build_issue_body(_crash(source=source))
    # 末尾 trailer ブロックに source 文字列がある
    trailer = body.split("## 直近ログ")[1]
    assert source in trailer


# ---------- build_issue_body: 環境 section is human-readable -------------


def test_body_env_section_is_human_readable_not_raw_dict():
    """hardware を `{'cpu_model': ..., 'gpu_model': ...}` の生 dict 文字列で
    そのまま貼り付けてはいけない (人間が読む Issue 本文なので)。"""
    body = build_issue_body(_crash())
    env_block = body.split("## 環境")[1].split("## スタックトレース")[0]
    # 生 dict repr は避ける
    assert "'cpu_model':" not in env_block
    assert "{'cpu_model'" not in env_block
    # 値そのものは現れる
    assert "Intel(R) Core(TM) i9-12900KF" in env_block
    assert "NVIDIA GeForce RTX 2080 Ti" in env_block
    assert "555.42" in env_block  # driver_version
    assert "Windows-11-10.0.26200-SP0" in env_block
    assert "3.12.4" in env_block


def test_body_env_section_labels_each_field():
    body = build_issue_body(_crash())
    env_block = body.split("## 環境")[1].split("## スタックトレース")[0]
    # 各行に人間可読ラベルがある (大文字小文字無視で確認)
    for label in ("CPU", "RAM", "GPU", "OS", "Python", "Disk"):
        assert label in env_block, f"env section missing label {label!r}"


def test_body_env_section_handles_unavailable_hardware():
    """採取失敗 ('<unavailable>') 値が env section にそのまま現れて落ちないこと。"""
    hw = {k: "<unavailable>" for k in _hw()}
    body = build_issue_body(_crash(hardware=hw))
    env_block = body.split("## 環境")[1].split("## スタックトレース")[0]
    assert "<unavailable>" in env_block


def test_body_env_section_handles_missing_hardware_keys():
    """hardware dict にキーが欠けていても KeyError を投げず、欠落値は
    '<unavailable>' 等のフォールバック表記になる。"""
    body = build_issue_body(_crash(hardware={"cpu_model": "x"}))
    env_block = body.split("## 環境")[1].split("## スタックトレース")[0]
    assert "x" in env_block  # 与えた値は出る
    # 欠落キーで例外が出ないこと (このアサーションに到達すれば OK)


# ---------- build_issue_body: code fence handling ------------------------


def test_body_traceback_is_in_code_fence():
    body = build_issue_body(_crash())
    trace_block = body.split("## スタックトレース")[1].split("## 直近ログ")[0]
    # fence は ``` または ~~~。少なくとも 1 ペアある
    assert ("```" in trace_block) or ("~~~" in trace_block)
    # trace 内容が現れる
    assert "apps/api/main.py" in trace_block


def test_body_log_tail_is_in_code_fence():
    body = build_issue_body(_crash())
    # ## 直近ログ より後 (trailer 前) に code fence + log 行
    log_block = body.split("## 直近ログ")[1]
    # 末尾 trailer (--- 区切り) より前の log 部分を狭める
    if "\n---\n" in log_block:
        log_block = log_block.split("\n---\n")[0]
    assert ("```" in log_block) or ("~~~" in log_block)
    # 各 log_tail の event_name が現れる
    assert "boot" in log_block
    assert "rag.search" in log_block


def test_body_handles_triple_backticks_in_traceback():
    """code fence injection 防御: traceback 自体が ``` を含む場合、
    生の ``` 言語タグで囲むと fence が早期終了し、その後の Markdown
    レンダリングが崩れる。実装は longer-fence (e.g. ````) または
    ~~~ fallback で対処する必要がある。"""
    malicious_trace = [
        '  File "x.py", line 1',
        "    raise RuntimeError('here is a fence: ``` and ~~~ both')",
        "RuntimeError: ``` mixed ~~~",
    ]
    body = build_issue_body(_crash(trace=malicious_trace))
    trace_block = body.split("## スタックトレース")[1].split("## 直近ログ")[0]
    # 内容自体は保持される (escape ではなく fence-extension)
    assert "``` and ~~~ both" in trace_block
    # body 全体がパースされた状態で、後段の `## 直近ログ` 見出しまで
    # 到達できる (= 仕掛けで本文が途切れない)
    assert "## 直近ログ" in body
    assert body.index("## 直近ログ") > body.index("## スタックトレース")


def test_body_handles_triple_backticks_in_log_tail():
    """log_tail 値 (str) に ``` が混ざっていても body が崩れない。"""
    crash = _crash(log_tail=[
        {"level": "INFO", "event_name": "weird```name"},
    ])
    body = build_issue_body(crash)
    assert "weird```name" in body
    # trailer まで到達できる
    assert "## 直近ログ" in body
    assert body.rindex("crash_id") > body.index("## 直近ログ")


# ---------- build_issue_body: edge cases ---------------------------------


def test_body_handles_empty_log_tail():
    body = build_issue_body(_crash(log_tail=[]))
    # セクション自体は存在する (空でも見出しは出す)
    assert "## 直近ログ" in body


def test_body_handles_empty_trace():
    body = build_issue_body(_crash(trace=[]))
    assert "## スタックトレース" in body


def test_body_handles_cjk_in_exception_message():
    body = build_issue_body(_crash(exception_message="日本語の例外メッセージ"))
    summary = body.split("## 環境")[0]
    assert "日本語の例外メッセージ" in summary


def test_body_handles_surrogate_pair_emoji_in_message():
    """emoji (surrogate pair) を含むメッセージで encode/decode が壊れない。"""
    body = build_issue_body(_crash(exception_message="boom \U0001F4A5"))
    assert "\U0001F4A5" in body


def test_body_log_tail_serialized_as_jsonl():
    """各 log event は 1 行 1 JSON で書かれる (jsonl)。"""
    crash = _crash(log_tail=[
        {"level": "INFO", "event_name": "a"},
        {"level": "WARN", "event_name": "b"},
    ])
    body = build_issue_body(crash)
    log_block = body.split("## 直近ログ")[1].split("\n---\n")[0]
    # 2 つの event が個別の有効な JSON 行として現れる
    json_lines = [
        line.strip()
        for line in log_block.splitlines()
        if line.strip().startswith("{") and line.strip().endswith("}")
    ]
    assert len(json_lines) == 2
    parsed = [json.loads(line) for line in json_lines]
    assert {p["event_name"] for p in parsed} == {"a", "b"}


# ---------- snapshot lock (output stability) ------------------------------


def test_body_snapshot_locks_format():
    """既知入力に対する body 全文を固定文字列で lock する。
    将来の format 変更時にこのテストを更新することで、フォーマット差分が
    レビュー単位で可視化される (= 偶発的なフォーマット崩れ検出)。"""
    crash = {
        "id": "fixed-id-001",
        "fingerprint": "fffffffffffffffffffffffffffffffffffffffff"[:40],
        "created_at": "2026-06-28T12:00:00Z",
        "exception_type": "ValueError",
        "exception_message": "bad input",
        "trace": ['  File "x.py", line 1', "ValueError: bad input"],
        "hardware": {
            "cpu_model": "CPU-X",
            "cpu_cores": 4,
            "cpu_threads": 8,
            "ram_total_gb": 16.0,
            "ram_available_gb": 8.0,
            "gpu_model": "GPU-Y",
            "gpu_vram_mb": 8192,
            "driver_version": "1.0",
            "os_arch": "x86_64",
            "os_platform": "Linux-test",
            "python_version": "3.12.0",
            "disk_free_gb": 100.0,
        },
        "log_tail": [{"level": "INFO", "event_name": "boot"}],
        "source": "fastapi",
    }
    body = build_issue_body(crash)
    expected = (
        "## 概要\n"
        "ValueError: bad input\n"
        "\n"
        "## 環境\n"
        "- CPU: CPU-X (4 cores / 8 threads)\n"
        "- RAM: 8.0 / 16.0 GB\n"
        "- GPU: GPU-Y (8192 MB, driver 1.0)\n"
        "- OS: Linux-test (x86_64)\n"
        "- Python: 3.12.0\n"
        "- Disk free: 100.0 GB\n"
        "\n"
        "## スタックトレース\n"
        "```\n"
        '  File "x.py", line 1\n'
        "ValueError: bad input\n"
        "```\n"
        "\n"
        "## 直近ログ (検疫済み)\n"
        "```jsonl\n"
        '{"level": "INFO", "event_name": "boot"}\n'
        "```\n"
        "\n"
        "---\n"
        "- crash_id: fixed-id-001\n"
        "- fingerprint: " + ("f" * 40) + "\n"
        "- source: fastapi\n"
    )
    assert body == expected


# ---------- build_issue_title --------------------------------------------


def test_title_starts_with_crash_prefix():
    assert build_issue_title(_crash()).startswith("[crash] ")


def test_title_contains_exception_type():
    title = build_issue_title(_crash(exception_type="RuntimeError"))
    assert "RuntimeError" in title


def test_title_contains_safe_message_when_short():
    title = build_issue_title(_crash(exception_message="boom"))
    assert "boom" in title


def test_title_length_under_80_for_short_message():
    title = build_issue_title(_crash(exception_message="boom"))
    assert len(title) <= 80


def test_title_length_capped_at_80_for_long_message():
    long_msg = "x" * 500
    title = build_issue_title(_crash(exception_message=long_msg))
    assert len(title) <= 80


def test_title_length_capped_at_80_for_cjk_message():
    """CJK は 1 文字あたり 3 byte だが、Issue title は文字数制限 (Unicode
    code point count) で OK。実装は code point 数で truncate する。"""
    cjk_msg = "あ" * 500
    title = build_issue_title(_crash(exception_message=cjk_msg))
    assert len(title) <= 80


def test_title_truncation_boundary_exact_80():
    """境界: ちょうど 80 文字に収まるメッセージは切り詰めない。"""
    # `[crash] RuntimeError: ` = 22 chars。残り 58 までは切らない。
    prefix_len = len("[crash] RuntimeError: ")
    msg = "x" * (80 - prefix_len)
    title = build_issue_title(_crash(exception_type="RuntimeError", exception_message=msg))
    assert len(title) == 80


def test_title_handles_empty_message():
    title = build_issue_title(_crash(exception_message=""))
    assert "[crash] RuntimeError" in title
    assert len(title) <= 80


# ---------- default_labels -----------------------------------------------


def test_default_labels_returns_crash_auto_and_needs_triage():
    labels = default_labels(_crash())
    assert labels == ["crash-auto", "needs-triage"]


@pytest.mark.parametrize(
    "source",
    sorted({"fastapi", "excepthook", "signal", "atexit", "frontend", "unclean_shutdown"}),
)
def test_default_labels_stable_across_sources(source):
    """default_labels は source に依らず安定。"""
    assert default_labels(_crash(source=source)) == ["crash-auto", "needs-triage"]


def test_default_labels_returns_new_list_each_call():
    """呼び出し側が破壊的に変更しても他コールに影響しない。"""
    a = default_labels(_crash())
    b = default_labels(_crash())
    a.append("mutated")
    assert b == ["crash-auto", "needs-triage"]

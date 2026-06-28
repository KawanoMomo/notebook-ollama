"""Tests for `core.crash_reporter.prefill_url`.

spec §10: GitHub Issue URL生成 (8KB制限対応).
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from core.crash_reporter import MAX_URL_LEN, REPO_SLUG, prefill_url
from core.crash_reporter.prefill_url import (
    FALLBACK_MARKER,
    LOG_SECTION_HEADER,
    TRIM_LINE_LEVELS,
    build_issue_url,
)


def _make_body(log_lines: list[str]) -> str:
    """Build a body matching the formatter (Task 2.3) Markdown shape.

    The log section uses the exact header that prefill_url looks for.
    """
    log_block = "\n".join(log_lines)
    if log_block:
        log_block = log_block + "\n"
    return (
        "## 概要\n"
        "RuntimeError: x\n\n"
        "## スタックトレース\n"
        "```\n"
        "Traceback (most recent call last):\n"
        "```\n\n"
        f"{LOG_SECTION_HEADER}\n"
        "```jsonl\n"
        f"{log_block}"
        "```\n\n"
        "---\n"
        "- crash_id: abc\n"
    )


def _parse_params(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query, keep_blank_values=True)


def _probe_pad_for_target(target_len: int) -> int:
    """Probe how many ASCII 'x' chars in a single log line make URL exactly target_len.

    The probe accounts for headers, fences, and the trailing newline so each
    boundary test computes its exact padding instead of guessing.
    """
    probe = 100
    probe_url, _ = build_issue_url(
        title="t", body=_make_body(["x" * probe]), labels=[]
    )
    # Each additional ASCII 'x' adds exactly 1 char to the URL (no encoding).
    return probe + (target_len - len(probe_url))


# ---------------------------------------------------------------------------
# Basic shape
# ---------------------------------------------------------------------------


def test_short_body_no_truncation():
    body = _make_body(['{"level":"INFO"}'])
    url, truncated = build_issue_url(
        title="boom", body=body, labels=["crash-auto"]
    )
    assert truncated is False
    assert f"github.com/{REPO_SLUG}/issues/new?" in url
    assert len(url) <= MAX_URL_LEN


def test_url_starts_with_default_repo():
    url, _ = build_issue_url(title="x", body=_make_body([]), labels=[])
    assert url.startswith(f"https://github.com/{REPO_SLUG}/issues/new?")


def test_custom_repo_overrides_default():
    url, _ = build_issue_url(
        title="x", body=_make_body([]), labels=[], repo="other/repo"
    )
    assert "https://github.com/other/repo/issues/new?" in url
    assert "KawanoMomo" not in url


def test_log_section_header_is_exposed():
    assert LOG_SECTION_HEADER == "## 直近ログ (検疫済み)"


def test_fallback_marker_mentions_drag_and_drop_local_log():
    assert "ログが長すぎて" in FALLBACK_MARKER
    assert "<crash_id>.log" in FALLBACK_MARKER


def test_trim_line_levels_are_descending_positive_ints():
    assert all(isinstance(n, int) and n > 0 for n in TRIM_LINE_LEVELS)
    assert TRIM_LINE_LEVELS == tuple(sorted(TRIM_LINE_LEVELS, reverse=True))
    # spec §10 explicitly lists [50, 30, 20, 10]
    assert TRIM_LINE_LEVELS == (50, 30, 20, 10)


# ---------------------------------------------------------------------------
# URL encoding
# ---------------------------------------------------------------------------


def test_japanese_title_url_encoded_and_roundtrips():
    url, _ = build_issue_url(title="例外発生", body=_make_body([]), labels=[])
    # raw kanji must not appear in URL (must be percent-encoded)
    assert "例外発生" not in url
    assert _parse_params(url)["title"][0] == "例外発生"


def test_labels_joined_by_comma():
    url, _ = build_issue_url(
        title="x",
        body=_make_body([]),
        labels=["crash-auto", "needs-triage"],
    )
    assert _parse_params(url)["labels"][0] == "crash-auto,needs-triage"


def test_empty_labels_list_is_empty_param():
    url, _ = build_issue_url(title="x", body=_make_body([]), labels=[])
    assert _parse_params(url)["labels"][0] == ""


@pytest.mark.parametrize("ch", ["&", "#", "?", "+", "=", "\n", " ", "/", "%"])
def test_special_characters_in_title_roundtrip(ch):
    title = f"A{ch}B"
    url, _ = build_issue_url(title=title, body=_make_body([]), labels=[])
    assert _parse_params(url)["title"][0] == title


@pytest.mark.parametrize("ch", ["&", "#", "?", "+", "=", "\n", " ", "/", "%"])
def test_special_characters_in_body_roundtrip(ch):
    body = _make_body([f'{{"x":"a{ch}b"}}'])
    url, _ = build_issue_url(title="t", body=body, labels=[])
    assert f"a{ch}b" in _parse_params(url)["body"][0]


def test_unicode_in_body_roundtrip():
    body = _make_body(['{"msg":"日本語テキスト🚀"}'])
    url, _ = build_issue_url(title="x", body=body, labels=[])
    assert "日本語テキスト🚀" in _parse_params(url)["body"][0]


def test_surrogate_safe_emoji_combining_sequence():
    # CJK + ZWJ emoji sequence — robustness against multi-code-unit chars.
    body = _make_body(['{"msg":"👨‍👩‍👧‍👦"}'])
    url, _ = build_issue_url(title="x", body=body, labels=[])
    assert "👨‍👩‍👧‍👦" in _parse_params(url)["body"][0]


# ---------------------------------------------------------------------------
# Progressive truncation
# ---------------------------------------------------------------------------


def test_long_body_triggers_progressive_truncation():
    lines = [f'{{"i":{i},"event":"x"}}' for i in range(1000)]
    body = _make_body(lines)
    url, truncated = build_issue_url(title="x", body=body, labels=["a"])
    assert truncated is True
    assert len(url) <= MAX_URL_LEN
    q = _parse_params(url)
    # title and labels survive truncation
    assert q["title"][0] == "x"
    assert q["labels"][0] == "a"
    # body still contains the non-log sections
    assert "## 概要" in q["body"][0]
    assert "## スタックトレース" in q["body"][0]


def test_extreme_body_falls_back_to_marker():
    # Few-but-huge lines so even keeping 10 lines is too big.
    lines = ["x" * 5000 for _ in range(3)]
    body = _make_body(lines)
    url, truncated = build_issue_url(title="x", body=body, labels=["a"])
    assert truncated is True
    assert len(url) <= MAX_URL_LEN
    decoded_body = _parse_params(url)["body"][0]
    assert "ログが長すぎて" in decoded_body
    assert "<crash_id>.log" in decoded_body


def test_oversized_50000_char_body_still_fits():
    body = _make_body(["a" * 50_000])
    url, truncated = build_issue_url(title="x", body=body, labels=["a"])
    assert truncated is True
    assert len(url) <= MAX_URL_LEN


def test_title_and_labels_preserved_when_body_fully_truncated():
    lines = ["x" * 5000 for _ in range(10)]
    body = _make_body(lines)
    url, _ = build_issue_url(
        title="big bug",
        body=body,
        labels=["crash-auto", "needs-triage"],
    )
    q = _parse_params(url)
    assert q["title"][0] == "big bug"
    assert q["labels"][0] == "crash-auto,needs-triage"


# ---------------------------------------------------------------------------
# Boundary at MAX_URL_LEN
# ---------------------------------------------------------------------------


def test_boundary_exact_max_url_len_no_truncation():
    pad = _probe_pad_for_target(MAX_URL_LEN)
    assert pad > 0, "fixture base URL too long; pad calc broken"
    body = _make_body(["x" * pad])
    url, truncated = build_issue_url(title="t", body=body, labels=[])
    assert len(url) == MAX_URL_LEN
    assert truncated is False


def test_boundary_just_below_max_url_len_no_truncation():
    pad = _probe_pad_for_target(MAX_URL_LEN - 1)
    body = _make_body(["x" * pad])
    url, truncated = build_issue_url(title="t", body=body, labels=[])
    assert len(url) == MAX_URL_LEN - 1
    assert truncated is False


def test_boundary_just_above_max_url_len_triggers_truncation():
    pad = _probe_pad_for_target(MAX_URL_LEN + 1)
    body = _make_body(["x" * pad])
    url, truncated = build_issue_url(title="t", body=body, labels=[])
    assert truncated is True
    assert len(url) <= MAX_URL_LEN


def test_empty_body_no_truncation():
    url, truncated = build_issue_url(title="x", body="", labels=[])
    assert truncated is False
    assert _parse_params(url)["body"][0] == ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def test_trim_log_section_keeps_tail_drops_head():
    # Use a fixed-width token so substrings of one index can't match another.
    body = _make_body([f"L{i:03d}END" for i in range(100)])
    trimmed = prefill_url._trim_log_section(body, 10)
    # tail (most-recent) lines must survive
    for i in range(90, 100):
        assert f"L{i:03d}END" in trimmed
    # earliest lines must be chopped
    for i in range(0, 90):
        assert f"L{i:03d}END" not in trimmed


def test_trim_log_section_no_op_when_already_small_enough():
    body = _make_body([f"line{i}" for i in range(5)])
    trimmed = prefill_url._trim_log_section(body, 10)
    assert trimmed == body


def test_trim_log_section_missing_section_returns_body_unchanged():
    body = "## 概要\n何もない\n"
    assert prefill_url._trim_log_section(body, 10) == body


def test_replace_log_section_inserts_marker():
    body = _make_body([f"L{i:03d}END" for i in range(10)])
    replaced = prefill_url._replace_log_section(body, FALLBACK_MARKER)
    assert FALLBACK_MARKER in replaced
    for i in range(10):
        assert f"L{i:03d}END" not in replaced
    # surrounding sections must remain
    assert "## 概要" in replaced
    assert "## スタックトレース" in replaced
    assert "---" in replaced


def test_replace_log_section_missing_section_returns_body_unchanged():
    body = "## 概要\n何もない\n"
    assert prefill_url._replace_log_section(body, "MARK") == body

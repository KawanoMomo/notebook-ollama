"""Tests for core.crash_reporter.redactor (whitelist-based PII filter).

spec: docs/specs/2026-06-28-crash-report-feedback-hub-design.md §6.2 / §6.3
"""
from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from core.crash_reporter import BLOCKED_LOG_KEYS
from core.crash_reporter.redactor import (
    ALLOWED_LOG_FIELDS,
    redact_exception_message,
    redact_log_event,
    redact_traceback,
)


class _DomainErr(Exception):
    safe_message = "Qdrant collection not found"


class _UnknownErr(Exception):
    pass


def test_allowed_fields_match_spec():
    must = {
        "level", "event_name", "timestamp", "request_id",
        "method", "path_pattern", "status_code", "duration_ms",
        "exception_type", "exception_module", "error_kind",
        "count", "n_chunks", "n_sources", "top_k",
        "model",
    }
    assert must <= ALLOWED_LOG_FIELDS


def test_redact_log_event_passes_whitelisted():
    ev = {
        "level": "ERROR", "event_name": "rag.search",
        "timestamp": "2026-06-28T00:00:00Z", "status_code": 500,
        "duration_ms": 42, "top_k": 8, "model": "qwen2.5:14b",
    }
    assert redact_log_event(ev) == ev


def test_redact_log_event_drops_event_with_blocked_key():
    ev = {
        "level": "INFO", "event_name": "x",
        "chunk_text": "leaked!",  # blocked
    }
    assert redact_log_event(ev) is None


def test_redact_log_event_strips_unknown_keys_but_keeps_whitelisted():
    ev = {
        "level": "INFO", "event_name": "x",
        "host_name": "my-laptop",  # not whitelisted, no leak
        "duration_ms": 1,
    }
    out = redact_log_event(ev)
    assert out == {"level": "INFO", "event_name": "x", "duration_ms": 1}


@pytest.mark.parametrize("key", sorted(BLOCKED_LOG_KEYS))
def test_redact_log_event_drops_all_blocked_keys(key):
    """Auto-covers any future addition to BLOCKED_LOG_KEYS.

    Previously the parametrize list was hand-rolled and silently lost
    coverage when BLOCKED_LOG_KEYS grew (source_id / question / doc_id /
    vector / chunk_id were missing). Driving the parametrize directly from
    the constant prevents that drift.
    """
    assert redact_log_event({"level": "INFO", "event_name": "x", key: "leak"}) is None


# --- must_fix 1: nested PII leak (recursive walk) ----------------------------


def test_redact_log_event_drops_nested_blocked_key_in_dict_value():
    """Regression: blocked key buried inside a nested dict must drop the event.

    The pre-fix implementation only inspected top-level keys, so
    {'level': 'INFO', 'model': {'chunk_text': 'leaked'}} slipped through
    unchanged because 'model' is whitelisted.
    """
    ev = {"level": "INFO", "model": {"chunk_text": "leaked"}}
    assert redact_log_event(ev) is None


def test_redact_log_event_drops_nested_blocked_key_in_list_of_dicts():
    """Regression: blocked key inside a list-of-dicts must drop the event."""
    ev = {"level": "INFO", "items": [{"prompt": "leak"}]}
    assert redact_log_event(ev) is None


def test_redact_log_event_drops_deeply_nested_blocked_key():
    """Triple-nested {dict -> list -> dict} forbidden key still detected."""
    ev = {
        "level": "INFO",
        "event_name": "x",
        "context": {"sources": [{"meta": {"answer": "should not leak"}}]},
    }
    assert redact_log_event(ev) is None


# --- must_fix 4: hostname / ip / mac / serial keys ---------------------------


@pytest.mark.parametrize("key", ["ip", "mac", "hostname", "serial"])
def test_redact_log_event_drops_hardware_identifiers_at_top_level(key):
    """Hardware/host identifiers must be treated as forbidden keys."""
    assert redact_log_event({"level": "INFO", "event_name": "x", key: "v"}) is None


def test_redact_log_event_drops_nested_ip_via_recursive_walk():
    """Nested 'ip' key under whitelisted 'model' is still detected."""
    ev = {"level": "INFO", "model": {"ip": "192.168.1.10"}}
    assert redact_log_event(ev) is None


# --- must_fix 2: hypothesis property-based test ------------------------------


_FORBIDDEN = frozenset(BLOCKED_LOG_KEYS) | {"ip", "mac", "hostname", "serial"}
_SAFE_KEYS = sorted(ALLOWED_LOG_FIELDS | {"foo", "bar", "baz", "extra"})

# Composite strategy: arbitrary nested dicts with a mix of safe and forbidden
# keys, and arbitrary text/number/bool leaf values.
_leaf = st.one_of(st.text(max_size=10), st.integers(), st.booleans(), st.none())


def _nested(depth: int) -> st.SearchStrategy:
    if depth == 0:
        return _leaf
    keys = st.sampled_from(_SAFE_KEYS + sorted(_FORBIDDEN))
    sub = _nested(depth - 1)
    return st.one_of(
        _leaf,
        st.dictionaries(keys, sub, max_size=4),
        st.lists(sub, max_size=4),
    )


def _contains_forbidden(value: object) -> bool:
    """True if any dict descendant has a key in _FORBIDDEN."""
    if isinstance(value, dict):
        for k, v in value.items():
            if k in _FORBIDDEN:
                return True
            if _contains_forbidden(v):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_forbidden(item) for item in value)
    return False


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(st.dictionaries(st.sampled_from(_SAFE_KEYS + sorted(_FORBIDDEN)), _nested(3),
                       max_size=6))
def test_redact_log_event_never_emits_forbidden_key_property(event):
    """Property: redact_log_event output never contains a forbidden key at any depth.

    Either the event is dropped entirely (None) when any descendant key is
    forbidden, or the output is a flat dict of whitelisted top-level keys
    with no nested dict carrying a forbidden key.
    """
    out = redact_log_event(event)
    if out is None:
        return
    # No forbidden key may appear anywhere in the output.
    assert not _contains_forbidden(out)
    # And every top-level key must be in the whitelist.
    assert all(k in ALLOWED_LOG_FIELDS for k in out)


# --- traceback redaction -----------------------------------------------------


def test_redact_traceback_strips_home_path(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    home_file = str(tmp_path / "secrets" / "doc.pdf")
    lines = [
        f'  File "{home_file}", line 1, in <module>',
        '  File "/usr/lib/python3.12/site-packages/fastapi/x.py", line 5',
    ]
    app_root = tmp_path / "app"  # 配下に何も無いケース
    out = redact_traceback(lines, app_root)
    assert "<HOME>" in out[0]
    assert str(tmp_path) not in out[0]
    # site-packages はそのまま残る
    assert "site-packages" in out[1]


# --- must_fix 5: Windows backslash path --------------------------------------


def test_redact_traceback_handles_windows_backslash_home(monkeypatch, tmp_path):
    """Windows-style traceback line with backslashes must be HOME-redacted."""
    fake_home = Path(r"C:\Users\momo")
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    lines = [
        r'  File "C:\Users\momo\Documents\secret.txt", line 1, in <module>',
    ]
    out = redact_traceback(lines, tmp_path / "app")
    assert "momo" not in out[0]
    assert "secret.txt" in out[0]  # 構造は残してファイル名は debugging に有用
    assert "<HOME>" in out[0]


def test_redact_traceback_handles_forward_slash_variant_of_windows_home(monkeypatch, tmp_path):
    """A traceback that uses forward slashes for a Windows HOME path must still match."""
    fake_home = Path(r"C:\Users\momo")
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    lines = [
        '  File "C:/Users/momo/Documents/secret.txt", line 1, in <module>',
    ]
    out = redact_traceback(lines, tmp_path / "app")
    assert "momo" not in out[0]
    assert "<HOME>" in out[0]


def test_redact_traceback_no_op_when_home_is_empty(monkeypatch, tmp_path):
    """Guard: an empty Path.home() must not turn every line into '<HOME><HOME>...'."""
    monkeypatch.setattr(Path, "home", lambda: Path(""))
    lines = ['  File "/usr/lib/python3.12/site-packages/fastapi/x.py", line 5']
    out = redact_traceback(lines, tmp_path / "app")
    assert out == lines


# --- exception message redaction ---------------------------------------------


def test_redact_exception_message_uses_safe_message_for_domain_error():
    assert redact_exception_message(_DomainErr("internal payload")) == "Qdrant collection not found"


def test_redact_exception_message_strips_unknown_exception_body():
    msg = redact_exception_message(_UnknownErr("doc_id=abc was missing"))
    # 型名 + モジュール名のみ。本文は出ない。
    assert "_UnknownErr" in msg
    assert "doc_id" not in msg
    assert "abc" not in msg

"""Tests for ``core.feedback_hub.feedback_formatter``.

spec §5.5 / §7.1 (POST /api/feedback-hub/feedback) — Sprint 3 Task 3.7.

Contract:
- ``build_feedback_issue_url(kind, body, sentiment, screenshot_url=None) -> str``
  returns a GitHub Issue prefill URL string.
- ``kind`` ∈ {feature, complaint, impression}; ``sentiment`` ∈
  {up, neutral, down, None}. Anything else → ``ValueError``.
- Empty / whitespace-only ``body`` → ``ValueError``.
- Resulting URL must be 8KB-safe (``len(url) <= MAX_URL_LEN``) for arbitrary body length.
- Labels query parameter must contain at least ``feedback`` + the kind.
- Body must contain the user's text (after URL-decode) for any kind / sentiment.
- ``screenshot_url`` (if provided) must appear in the body so reviewers can preview it.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from core.crash_reporter import MAX_URL_LEN, REPO_SLUG
from core.feedback_hub.feedback_formatter import (
    VALID_KINDS,
    VALID_SENTIMENTS,
    build_feedback_issue_url,
)


def _qs(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query, keep_blank_values=True)


# ----------------------------------------------------------------------
# constants / registry coverage
# ----------------------------------------------------------------------


def test_valid_kinds_are_the_three_documented():
    assert VALID_KINDS == frozenset({"feature", "complaint", "impression"})


def test_valid_sentiments_are_up_neutral_down():
    assert VALID_SENTIMENTS == frozenset({"up", "neutral", "down"})


# ----------------------------------------------------------------------
# happy path — parametrised over the FULL kind / sentiment registry
# ----------------------------------------------------------------------


@pytest.mark.parametrize("kind", sorted(VALID_KINDS))
def test_url_starts_with_github_issues_new_for_default_repo(kind):
    url = build_feedback_issue_url(kind=kind, body="hello", sentiment=None)
    assert url.startswith(f"https://github.com/{REPO_SLUG}/issues/new?")


@pytest.mark.parametrize("kind", sorted(VALID_KINDS))
def test_url_has_feedback_label_and_kind_label(kind):
    url = build_feedback_issue_url(kind=kind, body="hello", sentiment=None)
    labels = _qs(url)["labels"][0].split(",")
    assert "feedback" in labels
    assert kind in labels


@pytest.mark.parametrize("kind", sorted(VALID_KINDS))
@pytest.mark.parametrize(
    "sentiment", [*sorted(VALID_SENTIMENTS), None]  # type: ignore[arg-type]
)
def test_body_contains_user_text_for_every_kind_sentiment_pair(kind, sentiment):
    url = build_feedback_issue_url(
        kind=kind, body="my unique feedback text", sentiment=sentiment
    )
    body_decoded = _qs(url)["body"][0]
    assert "my unique feedback text" in body_decoded


@pytest.mark.parametrize("sentiment", sorted(VALID_SENTIMENTS))
def test_sentiment_appears_in_body_when_provided(sentiment):
    url = build_feedback_issue_url(
        kind="feature", body="hello", sentiment=sentiment
    )
    body_decoded = _qs(url)["body"][0]
    assert sentiment in body_decoded


def test_title_present_and_nonempty():
    url = build_feedback_issue_url(
        kind="feature", body="ノートブック作成時テンプレ選択", sentiment="up"
    )
    title = _qs(url)["title"][0]
    assert title.startswith("[feedback]")
    assert title.strip() != "[feedback]"


# ----------------------------------------------------------------------
# screenshot_url passthrough
# ----------------------------------------------------------------------


def test_screenshot_url_appears_in_body_when_provided():
    url = build_feedback_issue_url(
        kind="feature",
        body="hello",
        sentiment=None,
        screenshot_url="https://example.com/sshot.png",
    )
    body_decoded = _qs(url)["body"][0]
    assert "https://example.com/sshot.png" in body_decoded


def test_screenshot_url_absent_by_default():
    url = build_feedback_issue_url(kind="feature", body="hello", sentiment=None)
    body_decoded = _qs(url)["body"][0]
    assert "example.com" not in body_decoded


# ----------------------------------------------------------------------
# 8KB safety — fits regardless of body size
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "size", [10, 1_000, 10_000, 100_000]
)
def test_url_under_max_url_len_for_any_body_size(size):
    body = "x" * size
    url = build_feedback_issue_url(kind="feature", body=body, sentiment="up")
    assert len(url) <= MAX_URL_LEN, (
        f"body size {size} produced URL {len(url)} > MAX_URL_LEN {MAX_URL_LEN}"
    )


def test_url_under_max_url_len_for_unicode_heavy_body():
    # 日本語は URL エンコードで 1 文字 ≈ 9 バイト (`%E3%81%82` 等)。
    # 容量 8KB 制限を超えうるサイズで安全に収まることを確認する。
    body = "日本語のフィードバック文" * 3_000
    url = build_feedback_issue_url(kind="impression", body=body, sentiment="neutral")
    assert len(url) <= MAX_URL_LEN


# ----------------------------------------------------------------------
# input validation — raise ValueError at the boundary
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_kind",
    ["", "FEATURE", "bug", "ux", "category:feature", "feature ", " feature"],
)
def test_invalid_kind_raises_value_error(bad_kind):
    with pytest.raises(ValueError):
        build_feedback_issue_url(kind=bad_kind, body="x", sentiment=None)


@pytest.mark.parametrize("bad_sentiment", ["", "happy", "UP", "thumbs_up", "neutral "])
def test_invalid_sentiment_raises_value_error(bad_sentiment):
    with pytest.raises(ValueError):
        build_feedback_issue_url(kind="feature", body="x", sentiment=bad_sentiment)


@pytest.mark.parametrize("bad_body", ["", "   ", "\n\n", "\t"])
def test_empty_or_whitespace_body_raises_value_error(bad_body):
    with pytest.raises(ValueError):
        build_feedback_issue_url(kind="feature", body=bad_body, sentiment=None)


def test_none_kind_raises_type_or_value_error():
    with pytest.raises((TypeError, ValueError)):
        build_feedback_issue_url(kind=None, body="x", sentiment=None)  # type: ignore[arg-type]

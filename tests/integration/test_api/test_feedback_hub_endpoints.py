"""Integration tests for `/api/feedback-hub/*`.

spec §7.1 / plan Sprint 3 Task 3.7.

Endpoints:
- GET  /api/feedback-hub/notices       → seeded notices list
- GET  /api/feedback-hub/unread-count  → {count: int} (pending crashes for now)
- POST /api/feedback-hub/feedback      → {prefill_url: str}

Test policy:
- Use TestClient pattern with fresh `create_app()` per test (NOTEBOOK_OLLAMA_DATA_DIR
  pointed at tmp_path).
- Parametrise over all valid `kind` values from `VALID_KINDS` to avoid hand-rolled
  subsets going stale when the registry changes.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.crash_reporter import MAX_URL_LEN
from core.feedback_hub.feedback_formatter import VALID_KINDS


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    with TestClient(create_app()) as c:
        c._tmp_path = tmp_path  # type: ignore[attr-defined]
        yield c


# ----------------------------------------------------------------------
# GET /api/feedback-hub/notices
# ----------------------------------------------------------------------


def test_get_notices_returns_seed_data(client):
    r = client.get("/api/feedback-hub/notices")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "notices" in body
    assert isinstance(body["notices"], list)
    # 公開シードに少なくとも 1 件は含まれている。
    assert len(body["notices"]) >= 1
    for n in body["notices"]:
        assert set(("id", "date", "title", "body")).issubset(n.keys())
        assert isinstance(n["id"], str) and n["id"]
        assert isinstance(n["date"], str) and n["date"]
        assert isinstance(n["title"], str) and n["title"]
        assert isinstance(n["body"], str) and n["body"]


def test_get_notices_sorted_descending_by_date(client):
    r = client.get("/api/feedback-hub/notices")
    notices = r.json()["notices"]
    dates = [n["date"] for n in notices]
    assert dates == sorted(dates, reverse=True)


# ----------------------------------------------------------------------
# GET /api/feedback-hub/unread-count
# ----------------------------------------------------------------------


def test_unread_count_zero_when_no_pending_crashes(client):
    r = client.get("/api/feedback-hub/unread-count")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"count": 0}


def test_unread_count_includes_pending_crashes(client, tmp_path):
    # tmp_path == NOTEBOOK_OLLAMA_DATA_DIR (see fixture).
    from core.crash_reporter.pending_store import PendingCrash, save

    save(
        tmp_path,
        PendingCrash(
            id="crash-001",
            fingerprint="abc123",
            created_at="2026-06-28T12:00:00Z",
            exception_type="RuntimeError",
            exception_message="boom",
        ),
    )
    save(
        tmp_path,
        PendingCrash(
            id="crash-002",
            fingerprint="def456",
            created_at="2026-06-28T13:00:00Z",
            exception_type="ValueError",
            exception_message="bad",
        ),
    )
    r = client.get("/api/feedback-hub/unread-count")
    assert r.status_code == 200
    assert r.json() == {"count": 2}


# ----------------------------------------------------------------------
# POST /api/feedback-hub/feedback
# ----------------------------------------------------------------------


@pytest.mark.parametrize("kind", sorted(VALID_KINDS))
def test_post_feedback_returns_valid_prefill_url(client, kind):
    r = client.post(
        "/api/feedback-hub/feedback",
        json={"kind": kind, "body": "テストご意見", "sentiment": "up"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "prefill_url" in body
    url = body["prefill_url"]
    assert url.startswith("https://github.com/")
    # Labels include 'feedback' and the kind.
    labels = parse_qs(urlparse(url).query)["labels"][0].split(",")
    assert "feedback" in labels
    assert kind in labels


def test_post_feedback_without_sentiment_succeeds(client):
    r = client.post(
        "/api/feedback-hub/feedback",
        json={"kind": "impression", "body": "感想"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["prefill_url"].startswith("https://github.com/")


def test_post_feedback_with_too_long_body_returns_truncated_url(client):
    # 30_000 chars (pure ASCII) blows past MAX_URL_LEN (7000) and forces
    # `_safe_build_url` to truncate the body. Stays under the API max_length cap.
    huge_body = "x" * 30_000
    r = client.post(
        "/api/feedback-hub/feedback",
        json={"kind": "feature", "body": huge_body, "sentiment": "neutral"},
    )
    assert r.status_code == 200, r.text
    url = r.json()["prefill_url"]
    assert len(url) <= MAX_URL_LEN


def test_post_feedback_body_above_max_length_returns_422(client):
    """Pydantic 上限を超える body は 422 で弾く (DoS 対策の境界テスト)。"""
    r = client.post(
        "/api/feedback-hub/feedback",
        json={"kind": "feature", "body": "x" * 50_001},
    )
    assert r.status_code == 422


def test_post_feedback_with_screenshot_b64_succeeds(client):
    # Tiny base64 payload (does not need to be a real image — the endpoint
    # treats it as opaque and notes its presence in the body).
    tiny_png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "YAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )
    r = client.post(
        "/api/feedback-hub/feedback",
        json={
            "kind": "feature",
            "body": "スクショ添付テスト",
            "sentiment": "up",
            "screenshot_b64": tiny_png_b64,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["prefill_url"].startswith("https://github.com/")


# ----------------------------------------------------------------------
# validation errors
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_kind", ["bug", "ux", "FEATURE", "", "category:feature"]
)
def test_invalid_kind_returns_422(client, bad_kind):
    r = client.post(
        "/api/feedback-hub/feedback",
        json={"kind": bad_kind, "body": "x"},
    )
    assert r.status_code == 422


def test_missing_body_returns_422(client):
    r = client.post(
        "/api/feedback-hub/feedback",
        json={"kind": "feature"},
    )
    assert r.status_code == 422


def test_empty_body_returns_422(client):
    r = client.post(
        "/api/feedback-hub/feedback",
        json={"kind": "feature", "body": ""},
    )
    assert r.status_code == 422


@pytest.mark.parametrize("blank_body", ["   ", "\n", "\t  \n", "　　"])
def test_whitespace_only_body_returns_422(client, blank_body):
    """空白のみ body は 422 (HTTP 500 ではない) で弾く.

    回帰防止: Pydantic ``min_length=1`` だけでは ``'   '`` を通してしまい、
    下流 ``build_feedback_issue_url`` の ``ValueError`` が FastAPI の例外
    ハンドラで 500 に変換されていた。422 (semantic: valid JSON but
    unprocessable input) が正しい。
    """
    r = client.post(
        "/api/feedback-hub/feedback",
        json={"kind": "feature", "body": blank_body},
    )
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("bad_sentiment", ["happy", "UP", "thumbs_up"])
def test_invalid_sentiment_returns_422(client, bad_sentiment):
    r = client.post(
        "/api/feedback-hub/feedback",
        json={"kind": "feature", "body": "x", "sentiment": bad_sentiment},
    )
    assert r.status_code == 422

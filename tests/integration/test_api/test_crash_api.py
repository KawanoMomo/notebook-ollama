"""Integration tests for ``/api/crash/*``.

spec §7.1 / plan Sprint 3 Task 3.5.

Endpoints under test:
- ``GET    /api/crash/pending``               — list pending crashes
- ``POST   /api/crash/report``                — register a frontend crash
- ``POST   /api/crash/{id}/dismiss``          — drop a pending crash
- ``GET    /api/crash/{id}/prefill-url``      — GitHub Issue prefill URL
- ``POST   /api/crash/{id}/mark-reported``    — pending → reported transition

Test policy:
- Fresh ``create_app()`` per test via TestClient (existing pattern), with
  ``NOTEBOOK_OLLAMA_DATA_DIR`` pointed at ``tmp_path``.
- Parametrise over the FULL ``pending_store.Source`` registry (Literal
  args) for the source-pattern validation — never hand-roll subsets
  (lessons learned: hand-rolled subsets go stale silently).
- Validate prefill-url contract via ``urlparse`` rather than substring
  checks (avoids false-positives if encoding changes).
"""
from __future__ import annotations

from typing import get_args
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.crash_reporter import REPO_SLUG
from core.crash_reporter.pending_store import (
    PendingCrash,
    Source,
    load_all,
    save,
)
from core.crash_reporter.reported_store import is_reported


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Fresh app rooted at ``tmp_path`` (isolates pending / reported stores)."""
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    with TestClient(create_app()) as c:
        c._tmp_path = tmp_path  # type: ignore[attr-defined]
        yield c


def _valid_payload(message: str = "boom", source: str = "frontend") -> dict:
    """Minimal valid POST /report body."""
    return {
        "message": message,
        "stack": "Error: boom\n    at handler (app.js:42:10)",
        "hardware": {"gpu_model": "NVIDIA GeForce RTX 2080 Ti"},
        "source": source,
    }


# ----------------------------------------------------------------------
# GET /api/crash/pending
# ----------------------------------------------------------------------


def test_pending_empty_on_clean_data_dir(client):
    r = client.get("/api/crash/pending")
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_pending_lists_existing_files(client, tmp_path):
    """Files written directly under data_dir/crash-pending/ are returned."""
    save(
        tmp_path,
        PendingCrash(
            id="crash-existing-001",
            fingerprint="fpA",
            created_at="2026-06-28T12:00:00Z",
            exception_type="RuntimeError",
            exception_message="boom",
        ),
    )
    r = client.get("/api/crash/pending")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["id"] == "crash-existing-001"
    assert body[0]["fingerprint"] == "fpA"
    assert body[0]["exception_type"] == "RuntimeError"


# ----------------------------------------------------------------------
# POST /api/crash/report
# ----------------------------------------------------------------------


def test_report_with_valid_payload_returns_201_and_persists(client, tmp_path):
    r = client.post("/api/crash/report", json=_valid_payload(message="boom A"))
    assert r.status_code == 201, r.text
    body = r.json()
    # Schema sanity
    for key in (
        "id",
        "fingerprint",
        "created_at",
        "exception_type",
        "exception_message",
        "trace",
        "hardware",
        "log_tail",
        "source",
    ):
        assert key in body, f"missing key {key} in response"
    assert body["exception_message"] == "boom A"
    assert body["source"] == "frontend"
    assert body["exception_type"] == "FrontendError"
    # Subsequent GET shows exactly the one we just saved.
    r2 = client.get("/api/crash/pending")
    assert r2.status_code == 200
    pending = r2.json()
    assert len(pending) == 1
    assert pending[0]["id"] == body["id"]
    # Disk-side persistence sanity (atomic write hit the disk).
    on_disk = load_all(tmp_path)
    assert len(on_disk) == 1
    assert on_disk[0].id == body["id"]


def test_report_dedup_returns_200_with_existing_for_same_fingerprint(client):
    """Posting the same payload twice returns the existing pending (200, same id)."""
    first = client.post("/api/crash/report", json=_valid_payload(message="dup"))
    assert first.status_code == 201, first.text
    first_body = first.json()

    second = client.post("/api/crash/report", json=_valid_payload(message="dup"))
    assert second.status_code == 200, second.text
    second_body = second.json()

    # Same fingerprint AND same id (we returned the existing pending, not a new one).
    assert second_body["fingerprint"] == first_body["fingerprint"]
    assert second_body["id"] == first_body["id"]
    assert second_body["created_at"] == first_body["created_at"]

    # Pending list is not duplicated.
    pending = client.get("/api/crash/pending").json()
    assert len(pending) == 1


def test_report_returns_200_when_fingerprint_already_reported(client, tmp_path):
    """If reported_store already has the fingerprint, no save; 200 only."""
    # Round-trip 1: POST → mark-reported. After this the fingerprint lives in
    # reported_store and the pending file is gone.
    r1 = client.post("/api/crash/report", json=_valid_payload(message="known"))
    assert r1.status_code == 201, r1.text
    crash_id = r1.json()["id"]
    fingerprint = r1.json()["fingerprint"]
    r_mark = client.post(f"/api/crash/{crash_id}/mark-reported")
    assert r_mark.status_code == 200, r_mark.text
    assert is_reported(tmp_path, fingerprint)
    assert load_all(tmp_path) == []

    # Round-trip 2: same payload again. fingerprint already in reported_store
    # → server must NOT save a fresh pending and must return 200.
    r2 = client.post("/api/crash/report", json=_valid_payload(message="known"))
    assert r2.status_code == 200, r2.text
    assert r2.json()["fingerprint"] == fingerprint
    # No new pending file was created.
    assert load_all(tmp_path) == []
    assert client.get("/api/crash/pending").json() == []


def test_report_missing_message_returns_422(client):
    r = client.post("/api/crash/report", json={"stack": "x"})
    assert r.status_code == 422


def test_report_empty_message_returns_422(client):
    r = client.post("/api/crash/report", json={"message": ""})
    assert r.status_code == 422


def test_report_oversized_message_returns_422(client):
    r = client.post("/api/crash/report", json={"message": "x" * 4_001})
    assert r.status_code == 422


@pytest.mark.parametrize("bad_source", ["", "FRONTEND", "javascript", "user-input"])
def test_report_invalid_source_returns_422(client, bad_source):
    payload = _valid_payload()
    payload["source"] = bad_source
    r = client.post("/api/crash/report", json=payload)
    assert r.status_code == 422


@pytest.mark.parametrize("source", sorted(get_args(Source)))
def test_report_accepts_every_registered_source(client, source):
    """Lessons-learned: parametrise over the FULL registry, not hand-rolled subsets.

    Every value in ``pending_store.Source`` must be accepted by the
    Pydantic ``source`` pattern. If a new ``Source`` value is added,
    this test forces the router pattern to stay in sync.
    """
    payload = _valid_payload(message=f"source-{source}", source=source)
    r = client.post("/api/crash/report", json=payload)
    # 201 for first occurrence with that fingerprint (each source produces a
    # different stack-derived fingerprint though message differs too).
    assert r.status_code in (200, 201), r.text
    assert r.json()["source"] == source


# ----------------------------------------------------------------------
# POST /api/crash/{id}/dismiss
# ----------------------------------------------------------------------


def test_dismiss_missing_id_returns_404(client):
    r = client.post("/api/crash/does-not-exist/dismiss")
    assert r.status_code == 404


def test_dismiss_valid_id_returns_204_and_shrinks_pending(client):
    r1 = client.post("/api/crash/report", json=_valid_payload(message="todelete"))
    assert r1.status_code == 201
    crash_id = r1.json()["id"]
    assert len(client.get("/api/crash/pending").json()) == 1

    r2 = client.post(f"/api/crash/{crash_id}/dismiss")
    assert r2.status_code == 204
    assert r2.content == b""
    assert client.get("/api/crash/pending").json() == []

    # Second dismiss is now a 404 (idempotent in the sense of "no resurrection").
    r3 = client.post(f"/api/crash/{crash_id}/dismiss")
    assert r3.status_code == 404


# ----------------------------------------------------------------------
# GET /api/crash/{id}/prefill-url
# ----------------------------------------------------------------------


def test_prefill_url_missing_id_returns_404(client):
    r = client.get("/api/crash/does-not-exist/prefill-url")
    assert r.status_code == 404


def test_prefill_url_valid_id_returns_github_issue_url(client):
    r1 = client.post("/api/crash/report", json=_valid_payload(message="prefill me"))
    assert r1.status_code == 201
    crash_id = r1.json()["id"]

    r2 = client.get(f"/api/crash/{crash_id}/prefill-url")
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert set(body.keys()) == {"url", "truncated"}
    url = body["url"]
    expected_prefix = f"https://github.com/{REPO_SLUG}/issues/new"
    assert url.startswith(expected_prefix), url
    # truncated is False for a small payload.
    assert body["truncated"] is False

    # Sanity: query string carries title + body + labels.
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    assert "title" in qs and qs["title"][0].startswith("[crash] ")
    assert "body" in qs and "## 概要" in qs["body"][0]
    labels = qs["labels"][0].split(",")
    assert "crash-auto" in labels
    assert "needs-triage" in labels


# ----------------------------------------------------------------------
# POST /api/crash/{id}/mark-reported
# ----------------------------------------------------------------------


def test_mark_reported_missing_id_returns_404(client):
    r = client.post("/api/crash/does-not-exist/mark-reported")
    assert r.status_code == 404


def test_mark_reported_moves_crash_from_pending_to_reported(client, tmp_path):
    r1 = client.post("/api/crash/report", json=_valid_payload(message="filed"))
    assert r1.status_code == 201
    crash_id = r1.json()["id"]
    fingerprint = r1.json()["fingerprint"]

    # Before: pending has 1, reported_store has none for this fingerprint.
    assert len(load_all(tmp_path)) == 1
    assert not is_reported(tmp_path, fingerprint)

    r2 = client.post(f"/api/crash/{crash_id}/mark-reported")
    assert r2.status_code == 200, r2.text
    assert r2.json() == {"ok": True}

    # After: pending is empty, reported_store has the fingerprint.
    assert load_all(tmp_path) == []
    assert is_reported(tmp_path, fingerprint)
    assert client.get("/api/crash/pending").json() == []

    # Subsequent mark-reported on same id → 404 (already removed from pending).
    r3 = client.post(f"/api/crash/{crash_id}/mark-reported")
    assert r3.status_code == 404

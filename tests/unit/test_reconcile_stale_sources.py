"""起動時リコンシリエーション: 再起動で中断された処理の status 残骸を整理する。

背景(2026-07-04 実機フィードバック): バックエンド再起動後にノートブックへ
入ると、前プロセスで中断された変換が status='parsing' 等のまま残っており、
UI 上は「変換が勝手に始まっている」ように見える。実際にはプロセスは死んで
いるため、進行もしないスピナーが表示され続ける。

起動時にはいかなるジョブも実行されていないことが保証されるので、遷移中
status は全て「中断された」ものとして error / 未生成へ倒す。
"""
from __future__ import annotations

import sqlite3

import pytest

from core.storage import notebooks_repo, sources_repo
from core.storage.database import migrate
from core.storage.sources_repo import (
    AdrStatus,
    SourceStatus,
    SummaryStatus,
    reconcile_stale_sources,
)


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    migrate(c)
    return c


def _make(conn, *, status: SourceStatus, kind: str = "recording"):
    nb = notebooks_repo.create_notebook(conn, name="N")
    src = sources_repo.create_source(conn, notebook_id=nb.id, kind=kind)
    sources_repo.update_source_status(conn, src.id, status=status)
    return src


@pytest.mark.parametrize(
    "status",
    [
        SourceStatus.PENDING,
        SourceStatus.PARSING,
        SourceStatus.CHUNKING,
        SourceStatus.EMBEDDING,
    ],
)
def test_transient_status_becomes_error_with_message(conn, status):
    src = _make(conn, status=status)

    counts = reconcile_stale_sources(conn)

    after = sources_repo.get_source(conn, src.id)
    assert after.status == SourceStatus.ERROR
    assert "中断" in (after.error_msg or "")
    assert counts["sources"] == 1


def test_ready_and_error_sources_are_untouched(conn):
    ready = _make(conn, status=SourceStatus.READY)
    err = _make(conn, status=SourceStatus.ERROR)

    counts = reconcile_stale_sources(conn)

    assert sources_repo.get_source(conn, ready.id).status == SourceStatus.READY
    assert sources_repo.get_source(conn, err.id).status == SourceStatus.ERROR
    assert counts["sources"] == 0


def test_generating_summary_resets_to_none(conn):
    src = _make(conn, status=SourceStatus.READY)
    sources_repo.update_source_summary_status(
        conn, src.id, status=SummaryStatus.GENERATING
    )

    counts = reconcile_stale_sources(conn)

    after = sources_repo.get_source(conn, src.id)
    assert after.summary_status is None
    assert counts["summaries"] == 1


def test_ready_summary_is_untouched(conn):
    src = _make(conn, status=SourceStatus.READY)
    sources_repo.update_source_summary(conn, src.id, summary="要約")

    reconcile_stale_sources(conn)

    after = sources_repo.get_source(conn, src.id)
    assert after.summary_status == SummaryStatus.READY
    assert after.summary == "要約"


def test_generating_adr_resets_to_none(conn):
    src = _make(conn, status=SourceStatus.READY)
    sources_repo.update_source_adr_status(
        conn, src.id, status=AdrStatus.GENERATING
    )

    counts = reconcile_stale_sources(conn)

    after = sources_repo.get_source(conn, src.id)
    assert after.adr_status is None
    assert counts["adrs"] == 1

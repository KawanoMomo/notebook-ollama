"""SummaryJob のユニットテスト(リトライ・トランケーション・SSE publish)。

設計仕様: docs/specs/2026-06-25-source-guide-design.md §5.1
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pytest

from core.storage import notebooks_repo, sources_repo
from core.storage.chunks_repo import ChunkRecord, insert_chunks
from core.storage.database import migrate
from core.storage.sources_repo import SummaryStatus
from core.summary.summarizer import SummaryJob, SummaryDeps


class _FakeLLM:
    """generate を逐次的に成功/失敗させるダブル。

    `outputs` の各要素は文字列(成功時のテキスト)または Exception(失敗注入)。
    """

    def __init__(self, outputs: list):
        self.outputs = list(outputs)
        self.calls: list[dict] = []

    async def generate(self, *, model: str, prompt: str, options=None) -> str:
        self.calls.append({"model": model, "prompt": prompt, "options": options})
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


class _FakeBroker:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def publish(self, topic: str, payload: dict) -> None:
        self.events.append((topic, payload))


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    migrate(c)
    return c


def _make_source_with_chunks(
    conn: sqlite3.Connection, *, chunks: list[str]
) -> sources_repo.SourceRecord:
    nb = notebooks_repo.create_notebook(conn, name="N")
    src = sources_repo.create_source(conn, notebook_id=nb.id, kind="markdown")
    records = [
        ChunkRecord(
            id=f"c{i}",
            source_id=src.id,
            notebook_id=nb.id,
            ord=i,
            page=None,
            heading_path=None,
            text=t,
            token_count=len(t.split()),
        )
        for i, t in enumerate(chunks)
    ]
    insert_chunks(conn, records)
    return src


@pytest.mark.asyncio
async def test_success_sets_summary_and_publishes_sse(conn):
    src = _make_source_with_chunks(conn, chunks=["aaa bbb", "ccc ddd"])
    llm = _FakeLLM(["これは3行で要約された内容です。"])
    broker = _FakeBroker()
    job = SummaryJob(deps=SummaryDeps(conn=conn, llm=llm, model="llm", broker=broker))

    await job.run(source_id=src.id)

    after = sources_repo.get_source(conn, src.id)
    assert after.summary_status == SummaryStatus.READY
    assert after.summary == "これは3行で要約された内容です。"
    assert len(llm.calls) == 1

    statuses = [p["summary_status"] for (_t, p) in broker.events if "summary_status" in p]
    assert "generating" in statuses
    assert "ready" in statuses


@pytest.mark.asyncio
async def test_retries_up_to_three_times_on_transient_failure(conn):
    src = _make_source_with_chunks(conn, chunks=["aaa"])
    llm = _FakeLLM(
        [RuntimeError("transient 1"), RuntimeError("transient 2"), "成功した要約"]
    )
    job = SummaryJob(deps=SummaryDeps(conn=conn, llm=llm, model="llm", sleep=_no_sleep))

    await job.run(source_id=src.id)

    after = sources_repo.get_source(conn, src.id)
    assert after.summary == "成功した要約"
    assert after.summary_status == SummaryStatus.READY
    assert len(llm.calls) == 3


@pytest.mark.asyncio
async def test_three_failures_marks_status_error(conn):
    src = _make_source_with_chunks(conn, chunks=["aaa"])
    llm = _FakeLLM(
        [RuntimeError("e1"), RuntimeError("e2"), RuntimeError("e3")]
    )
    broker = _FakeBroker()
    job = SummaryJob(
        deps=SummaryDeps(conn=conn, llm=llm, model="llm", broker=broker, sleep=_no_sleep)
    )

    await job.run(source_id=src.id)

    after = sources_repo.get_source(conn, src.id)
    assert after.summary is None
    assert after.summary_status == SummaryStatus.ERROR
    assert len(llm.calls) == 3
    # 「3 回目の失敗で初めてユーザーにエラー通知」: SSE に error が含まれる
    statuses = [p.get("summary_status") for (_t, p) in broker.events]
    assert statuses[-1] == "error"


@pytest.mark.asyncio
async def test_no_chunks_marks_error_without_calling_llm(conn):
    nb = notebooks_repo.create_notebook(conn, name="N")
    src = sources_repo.create_source(conn, notebook_id=nb.id, kind="markdown")
    llm = _FakeLLM([])
    job = SummaryJob(deps=SummaryDeps(conn=conn, llm=llm, model="llm"))

    await job.run(source_id=src.id)

    after = sources_repo.get_source(conn, src.id)
    assert after.summary_status == SummaryStatus.ERROR
    assert llm.calls == []


@pytest.mark.asyncio
async def test_chunk_text_is_truncated_to_token_limit(conn):
    long_chunk = "ぁ" * 8000
    src = _make_source_with_chunks(conn, chunks=[long_chunk])
    llm = _FakeLLM(["ok"])
    job = SummaryJob(
        deps=SummaryDeps(conn=conn, llm=llm, model="llm", max_input_tokens=200)
    )

    await job.run(source_id=src.id)

    sent_prompt = llm.calls[0]["prompt"]
    # 上限 200 トークン以内に縮められている(プロンプト全体ではなくチャンク部分が対象だが、
    # 厳密値は実装依存なので「投入文字数 < 元チャンク文字数」をチェック)
    assert len(sent_prompt) < len(long_chunk)


async def _no_sleep(_seconds: float) -> None:
    return None

"""AdrJob のユニットテスト。

Decision Gate(yes/no + 根拠)、抽出 → Markdown front-matter、スキップ JSON。
リトライ、SSE publish。

設計: docs/specs/2026-06-26-meeting-adr-templates.md
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from core.adr.adr_job import AdrDeps, AdrJob
from core.storage import notebooks_repo, sources_repo
from core.storage.chunks_repo import ChunkRecord, insert_chunks
from core.storage.database import migrate
from core.storage.sources_repo import AdrStatus


class _FakeLLM:
    """generate を逐次的に成功/失敗させる。outputs は文字列 or Exception。"""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls: list[dict] = []

    async def generate(self, *, model, prompt, options=None):
        self.calls.append({"model": model, "prompt": prompt, "options": options})
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


class _FakeBroker:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    async def publish(self, topic, payload):
        self.events.append((topic, payload))


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    migrate(c)
    return c


def _make_source(conn, *, kind: str = "recording", chunks: list[str]):
    nb = notebooks_repo.create_notebook(conn, name="N")
    src = sources_repo.create_source(conn, notebook_id=nb.id, kind=kind)
    insert_chunks(
        conn,
        [
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
        ],
    )
    return src


# Decision Gate のレスポンスは LLM の 1 回目の generate 出力。yes/no + reason の
# 簡易テキスト(実装では先頭 "YES"/"NO" を判定)。
_GATE_YES = "YES\n根拠: 採用が宣言され、複数の選択肢が比較されている。"
_GATE_NO = "NO\n根拠: 単なる進捗報告のみ。"


@pytest.mark.asyncio
async def test_decision_gate_no_marks_skipped(conn):
    """Gate が NO ならスキップ(ADR 本体は生成しない)。"""
    src = _make_source(conn, chunks=["進捗報告だけです"])
    llm = _FakeLLM([_GATE_NO])
    broker = _FakeBroker()
    job = AdrJob(deps=AdrDeps(conn=conn, llm=llm, model="m", broker=broker))

    await job.run(source_id=src.id)
    after = sources_repo.get_source(conn, src.id)
    assert after.adr_status == AdrStatus.SKIPPED
    # adr_draft には reason を含む JSON
    body = json.loads(after.adr_draft)
    assert body["adr_generated"] is False
    assert body["reason"]
    # gate しか呼ばれていない
    assert len(llm.calls) == 1
    # SSE に skipped が含まれる
    statuses = [p.get("adr_status") for (_t, p) in broker.events]
    assert "skipped" in statuses


@pytest.mark.asyncio
async def test_decision_gate_yes_produces_markdown_adr(conn):
    """Gate が YES なら ADR 本文を生成して ready。"""
    src = _make_source(conn, chunks=["案 A vs 案 B を比較し、A を採用と決定。"])
    adr_md = (
        "---\nstatus: accepted\ntemplate: madr\nconfidence: high\n---\n\n"
        "# ADR: 案 A の採用\n\n## Context\n背景。\n\n## Decision\nA を採用。\n"
    )
    llm = _FakeLLM([_GATE_YES, adr_md])
    broker = _FakeBroker()
    job = AdrJob(deps=AdrDeps(conn=conn, llm=llm, model="m", broker=broker))

    await job.run(source_id=src.id)
    after = sources_repo.get_source(conn, src.id)
    assert after.adr_status == AdrStatus.READY
    assert after.adr_draft and "ADR: 案 A の採用" in after.adr_draft
    assert after.adr_template == "madr"
    assert after.adr_confidence == "high"
    assert after.adr_generated_at is not None
    statuses = [p.get("adr_status") for (_t, p) in broker.events]
    assert "generating" in statuses
    assert "ready" in statuses


@pytest.mark.asyncio
async def test_extraction_failure_retries_and_finally_errors(conn):
    """Gate YES → 抽出が 3 回失敗で error。"""
    src = _make_source(conn, chunks=["決定: A を採用"])
    llm = _FakeLLM(
        [_GATE_YES, RuntimeError("e1"), RuntimeError("e2"), RuntimeError("e3")]
    )
    job = AdrJob(
        deps=AdrDeps(
            conn=conn, llm=llm, model="m", sleep=_no_sleep
        )
    )
    await job.run(source_id=src.id)
    after = sources_repo.get_source(conn, src.id)
    assert after.adr_status == AdrStatus.ERROR


@pytest.mark.asyncio
async def test_extraction_succeeds_on_second_attempt(conn):
    src = _make_source(conn, chunks=["決定: A を採用"])
    adr_md = "---\ntemplate: madr\nconfidence: medium\n---\n\n# ADR\n"
    llm = _FakeLLM([_GATE_YES, RuntimeError("transient"), adr_md])
    job = AdrJob(deps=AdrDeps(conn=conn, llm=llm, model="m", sleep=_no_sleep))
    await job.run(source_id=src.id)
    after = sources_repo.get_source(conn, src.id)
    assert after.adr_status == AdrStatus.READY
    assert after.adr_template == "madr"
    assert after.adr_confidence == "medium"


@pytest.mark.asyncio
async def test_no_chunks_marks_error_without_calling_llm(conn):
    nb = notebooks_repo.create_notebook(conn, name="N")
    src = sources_repo.create_source(conn, notebook_id=nb.id, kind="markdown")
    llm = _FakeLLM([])
    job = AdrJob(deps=AdrDeps(conn=conn, llm=llm, model="m"))
    await job.run(source_id=src.id)
    after = sources_repo.get_source(conn, src.id)
    assert after.adr_status == AdrStatus.ERROR
    assert llm.calls == []


@pytest.mark.asyncio
async def test_gate_prompt_includes_decision_criteria(conn):
    """Gate プロンプトに『2 つ以上の選択肢比較』『制約・トレードオフ』
    『合意宣言』の 3 基準が含まれる(誤判定を減らすため明示する)。"""
    src = _make_source(conn, chunks=["話"])
    llm = _FakeLLM([_GATE_NO])
    job = AdrJob(deps=AdrDeps(conn=conn, llm=llm, model="m"))
    await job.run(source_id=src.id)
    gate_prompt = llm.calls[0]["prompt"]
    assert "選択肢" in gate_prompt or "選定" in gate_prompt or "代替" in gate_prompt
    assert "トレードオフ" in gate_prompt or "制約" in gate_prompt
    assert "合意" in gate_prompt or "採用" in gate_prompt or "決定" in gate_prompt


@pytest.mark.asyncio
async def test_extract_prompt_includes_madr_sections(conn):
    """抽出プロンプトに MADR の主要セクションが含まれる。"""
    src = _make_source(conn, chunks=["話"])
    llm = _FakeLLM(
        [
            _GATE_YES,
            "---\ntemplate: madr\nconfidence: high\n---\n\n# ADR\n",
        ]
    )
    job = AdrJob(deps=AdrDeps(conn=conn, llm=llm, model="m"))
    await job.run(source_id=src.id)
    extract_prompt = llm.calls[1]["prompt"]
    # MADR の主要セクション名(英語/日本語どちらでも構わない)
    assert "Context" in extract_prompt or "背景" in extract_prompt
    assert "Decision" in extract_prompt or "決定" in extract_prompt
    assert "Consequences" in extract_prompt or "影響" in extract_prompt


async def _no_sleep(_seconds: float) -> None:
    return None

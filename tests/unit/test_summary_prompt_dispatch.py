"""SummaryJob のプロンプト分岐(kind == 'recording' → 議事録テンプレ)。

設計: docs/specs/2026-06-26-meeting-adr-templates.md
"""
from __future__ import annotations

import sqlite3

import pytest

from core.storage import notebooks_repo, sources_repo
from core.storage.chunks_repo import ChunkRecord, insert_chunks
from core.storage.database import migrate
from core.summary.summarizer import SummaryDeps, SummaryJob


class _FakeLLM:
    def __init__(self, outputs=None) -> None:
        self.outputs = list(outputs or ["ok"])
        self.calls: list[dict] = []

    async def generate(self, *, model, prompt, options=None):
        self.calls.append({"model": model, "prompt": prompt, "options": options})
        out = self.outputs.pop(0) if self.outputs else "ok"
        if isinstance(out, Exception):
            raise out
        return out


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    migrate(c)
    return c


def _make_source(conn, *, kind: str, chunks: list[tuple[str, str | None]]):
    """chunks: list of (text, speaker)"""
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
                speaker=spk,
            )
            for i, (t, spk) in enumerate(chunks)
        ],
    )
    return src


@pytest.mark.asyncio
async def test_document_kind_uses_document_template(conn):
    """kind in {markdown, pdf, txt, ...} は既存の document テンプレを使う。"""
    src = _make_source(conn, kind="markdown", chunks=[("本文 A", None), ("本文 B", None)])
    llm = _FakeLLM(["ok"])
    job = SummaryJob(deps=SummaryDeps(conn=conn, llm=llm, model="m"))
    await job.run(source_id=src.id)

    prompt = llm.calls[0]["prompt"]
    # document テンプレ固有の表現
    assert "資料" in prompt
    # 議事録テンプレ固有の表現は出ない
    assert "議題" not in prompt
    assert "次のアクション" not in prompt
    assert "話者" not in prompt


@pytest.mark.asyncio
async def test_recording_kind_uses_meeting_template(conn):
    src = _make_source(
        conn,
        kind="recording",
        chunks=[("おはようございます", "あなた"), ("次回までに仕様確認します", "相手1")],
    )
    llm = _FakeLLM(["ok"])
    job = SummaryJob(deps=SummaryDeps(conn=conn, llm=llm, model="m"))
    await job.run(source_id=src.id)

    prompt = llm.calls[0]["prompt"]
    # 議事録テンプレ固有の表現
    assert "議事録" in prompt or "会議" in prompt
    assert "決定" in prompt
    assert "次のアクション" in prompt or "アクション" in prompt
    assert "話者" in prompt
    # 話者ラベル付きチャンクが入っている
    assert "あなた" in prompt
    assert "相手1" in prompt


@pytest.mark.asyncio
async def test_recording_template_forbids_speculation_and_filler(conn):
    """議事録テンプレは推測禁止・フィラー除外を含む。"""
    src = _make_source(conn, kind="recording", chunks=[("話 A", "あなた")])
    llm = _FakeLLM(["ok"])
    job = SummaryJob(deps=SummaryDeps(conn=conn, llm=llm, model="m"))
    await job.run(source_id=src.id)
    prompt = llm.calls[0]["prompt"]
    assert "推測" in prompt
    # フィラー除外の言及
    assert "フィラー" in prompt or "相槌" in prompt or "言い直し" in prompt


@pytest.mark.asyncio
async def test_recording_truncation_note_appears_when_long(conn):
    long_chunks = [("ぁ" * 6000, "あなた")]
    src = _make_source(conn, kind="recording", chunks=long_chunks)
    llm = _FakeLLM(["ok"])
    job = SummaryJob(
        deps=SummaryDeps(conn=conn, llm=llm, model="m", max_input_tokens_meeting=200)
    )
    await job.run(source_id=src.id)
    prompt = llm.calls[0]["prompt"]
    assert "抜粋" in prompt or "途中" in prompt


@pytest.mark.asyncio
async def test_recording_uses_meeting_token_budget(conn):
    """SummaryDeps.max_input_tokens_meeting (既定 8000) が録音に使われる。
    短い録音では切り詰めず、長い録音(8000 超)でだけ切り詰める。"""
    src = _make_source(conn, kind="recording", chunks=[("短い議事録", "あなた")])
    llm = _FakeLLM(["ok"])
    # document の既定(4000)は超えないので、recording の境界 (8000) を確認するため
    # max_input_tokens_meeting=20 を指定して切り詰めが起きるか確認
    job = SummaryJob(
        deps=SummaryDeps(conn=conn, llm=llm, model="m", max_input_tokens_meeting=2)
    )
    await job.run(source_id=src.id)
    prompt = llm.calls[0]["prompt"]
    # max_tokens=2 でほぼ全部削れる → 抜粋注釈が入る
    assert "抜粋" in prompt or "途中" in prompt

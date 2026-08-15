"""spans が messages に保存され、再読込で戻ることを確認する。

セットアップは tests/integration/test_conversations_repo.py の書き方に倣う
(tests/integration に conftest.py は無く、各テストが tmp_path から DB を作る)。
"""

import pytest

from core.storage.conversations_repo import create_conversation
from core.storage.database import connect, migrate
from core.storage.messages_repo import append_message, list_messages
from core.storage.notebooks_repo import create_notebook


def _ctx(tmp_path):
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    conv = create_conversation(conn, notebook_id=nb.id, title="t")
    return conn, conv


def test_spans_round_trip_through_messages(tmp_path):
    conn, conv = _ctx(tmp_path)
    citations = [
        {
            "n": 1,
            "chunk_id": "c1",
            "source_id": "s1",
            "source_title": "t",
            "location": "p.1",
            "url_or_path": None,
            "snippet": "x",
            "audio_source_id": None,
            "audio_start_ms": None,
            "audio_channel": None,
            "spans": [
                {
                    "answer_occurrence": 0,
                    "ordinal": 1,
                    "start": 3,
                    "end": 9,
                    "quote": "abcdef",
                    "method": "lexical",
                }
            ],
        }
    ]
    append_message(
        conn,
        conversation_id=conv.id,
        role="assistant",
        content="answer[^1]",
        citations=citations,
        model="m",
    )
    rows = list_messages(conn, conversation_id=conv.id)
    assert rows[-1].citations[0]["spans"][0]["quote"] == "abcdef"


def test_legacy_citation_without_spans_is_readable(tmp_path):
    conn, conv = _ctx(tmp_path)
    append_message(
        conn,
        conversation_id=conv.id,
        role="assistant",
        content="answer[^1]",
        citations=[{"n": 1, "chunk_id": "c1"}],
        model="m",
    )
    rows = list_messages(conn, conversation_id=conv.id)
    assert rows[-1].citations[0].get("spans", []) == []


# --- 第1段が生成経路に接続されていることの確認 -------------------------------
# 上の2本は永続化層(JSON 列)の往復だけを見ており、spans 未実装でも通ってしまう。
# 生成経路(stream / MCP ask)に attach_evidence_spans が繋がっていることは、
# done イベントと ask_tool の戻り値で直接確かめる。

CHUNK_TEXT = "レベル2では成果物が管理され、作業生産物の構成管理が行われる。"
ANSWER_TOKENS = ["レベル2では", "成果物が管理される", "[^1]"]


def _hit():
    from core.retrieval.search import RetrievedChunk

    return RetrievedChunk(
        chunk_id="c1",
        source_id="s1",
        source_title="PAM",
        source_kind="pdf",
        page=42,
        heading_path="§3",
        ord=0,
        text=CHUNK_TEXT,
        token_count=10,
        score=0.9,
    )


class _SpanRetrieval:
    async def search(self, *, notebook_id, query, limit, source_ids=None):
        return [_hit()]


class _SpanGateway:
    async def chat_stream(self, *, model, messages, options=None, meta=None):
        for tok in ANSWER_TOKENS:
            yield tok
        if meta is not None:
            meta["done_reason"] = "stop"


@pytest.mark.asyncio
async def test_generation_done_event_carries_evidence_spans():
    from core.generation.stream import GenerationDeps, GenerationService

    svc = GenerationService(
        deps=GenerationDeps(retrieval=_SpanRetrieval(), ollama=_SpanGateway())
    )
    events = [
        ev
        async for ev in svc.run(
            notebook_id="nb",
            model="qwen2.5:14b",
            question="質問",
            history=[],
            num_ctx=8192,
            context_budget_ratio=0.8,
            response_budget_tokens=1024,
            retrieval_top_k=8,
            min_history_turns=1,
        )
    ]
    final = next(e for e in events if e.kind == "done")
    spans = final.data["citations"][0]["spans"]
    assert len(spans) == 1
    assert spans[0]["answer_occurrence"] == 0
    assert spans[0]["ordinal"] == 1
    assert spans[0]["method"] == "lexical"
    assert spans[0]["quote"] == CHUNK_TEXT[spans[0]["start"] : spans[0]["end"]]
    assert "成果物が管理され" in spans[0]["quote"]


class _AskRetrieval:
    async def search(self, *, notebook_id, query, limit):
        return [_hit()]


class _AskClient:
    async def show(self, model):
        return {"parameters": "num_ctx 8192"}


@pytest.mark.asyncio
async def test_mcp_ask_carries_evidence_spans():
    """MCP 経由の回答だけ spans 無しになるのを防ぐ(計画 Task 5 Files)。"""
    from types import SimpleNamespace

    from core.mcp.tools.ask import ask_tool

    result = await ask_tool(
        notebook_id="nb1",
        question="?",
        model=None,
        style="concise",
        retrieval=_AskRetrieval(),
        ollama=_SpanGateway(),
        client=_AskClient(),
        config=SimpleNamespace(
            visual=SimpleNamespace(search_strategy="hybrid_rrf"),
            generation=SimpleNamespace(
                context_budget_ratio=0.8, response_budget_tokens=512, auto_continue_max=2
            ),
            retrieval=SimpleNamespace(top_k=8, min_history_turns=0),
            ollama=SimpleNamespace(default_model="qwen2.5:14b"),
        ),
        notebook_default_model=None,
    )
    spans = result["citations"][0]["spans"]
    assert len(spans) == 1
    assert spans[0]["method"] == "lexical"
    assert "成果物が管理され" in spans[0]["quote"]

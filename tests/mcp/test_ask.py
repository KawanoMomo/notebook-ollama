import pytest

from core.mcp.tools.ask import ask_tool
from core.retrieval.search import RetrievedChunk


class FakeRetrieval:
    async def search(self, *, notebook_id, query, limit):
        return [
            RetrievedChunk(
                chunk_id="c1",
                source_id="s1",
                source_title="ARM",
                source_kind="pdf",
                page=42,
                heading_path="§3",
                ord=0,
                text="Cortex content.",
                token_count=4,
                score=0.9,
            ),
        ]


class FakeGateway:
    async def chat_stream(self, *, model, messages, options=None, meta=None):
        for tok in ["answer ", "[^1]"]:
            yield tok


class FakeClient:
    async def show(self, model):
        return {"parameters": "num_ctx 8192"}


class FakeNotebooks:
    def get(self, nb_id):
        return self

    name = "N"
    default_model = "qwen2.5:14b"


@pytest.mark.asyncio
async def test_ask_returns_answer_and_citations():
    from types import SimpleNamespace

    result = await ask_tool(
        notebook_id="nb1",
        question="?",
        model=None,
        style="concise",
        retrieval=FakeRetrieval(),
        ollama=FakeGateway(),
        client=FakeClient(),
        config=SimpleNamespace(
            generation=SimpleNamespace(
                context_budget_ratio=0.8, response_budget_tokens=512, auto_continue_max=2
            ),
            retrieval=SimpleNamespace(top_k=8, min_history_turns=0),
            ollama=SimpleNamespace(default_model="qwen2.5:14b"),
        ),
        notebook_default_model=None,
    )
    assert "answer" in result["answer"]
    assert result["citations"][0]["source_title"] == "ARM"
    assert result["citations"][0]["location"] == "p.42, §3"
    assert result["model_used"] == "qwen2.5:14b"


class SequenceGateway:
    """round ごとに (tokens, done_reason) を返す fake。prefill 検証用に
    受け取った messages を記録する。

    tests/integration/test_generation.py の SequenceGateway と同じ形。
    """

    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.received_messages: list[list[dict]] = []
        self.calls = 0

    async def chat_stream(self, *, model, messages, options=None, meta=None):
        self.received_messages.append(list(messages))
        tokens, reason = self.rounds[self.calls]
        self.calls += 1
        for t in tokens:
            yield t
        if meta is not None:
            meta["done_reason"] = reason


@pytest.mark.asyncio
async def test_ask_auto_continues_on_length():
    from types import SimpleNamespace

    gw = SequenceGateway([(["前半"], "length"), (["後半"], "stop")])
    result = await ask_tool(
        notebook_id="nb1",
        question="?",
        model=None,
        style="concise",
        retrieval=FakeRetrieval(),
        ollama=gw,
        client=FakeClient(),
        config=SimpleNamespace(
            generation=SimpleNamespace(
                context_budget_ratio=0.8, response_budget_tokens=512, auto_continue_max=2
            ),
            retrieval=SimpleNamespace(top_k=8, min_history_turns=0),
            ollama=SimpleNamespace(default_model="qwen2.5:14b"),
        ),
        notebook_default_model=None,
    )
    assert result["answer"] == "前半後半"
    # 2回目のリクエスト末尾は途中応答の assistant prefill(トリアージ#10)
    assert gw.received_messages[1][-1] == {"role": "assistant", "content": "前半"}


@pytest.mark.asyncio
async def test_ask_appends_note_when_exhausted():
    from types import SimpleNamespace

    gw = SequenceGateway([(["a"], "length"), (["b"], "length"), (["c"], "length")])
    result = await ask_tool(
        notebook_id="nb1",
        question="?",
        model=None,
        style="concise",
        retrieval=FakeRetrieval(),
        ollama=gw,
        client=FakeClient(),
        config=SimpleNamespace(
            generation=SimpleNamespace(
                context_budget_ratio=0.8, response_budget_tokens=512, auto_continue_max=2
            ),
            retrieval=SimpleNamespace(top_k=8, min_history_turns=0),
            ollama=SimpleNamespace(default_model="qwen2.5:14b"),
        ),
        notebook_default_model=None,
    )
    assert "打ち切られました" in result["answer"]


@pytest.mark.asyncio
async def test_ask_continuation_error_degrades_gracefully():
    """core/generation/stream.py の同処理と同じ graceful degradation(R7)。

    2ラウンド目(継続ラウンド)の AppError で答え全体を失わず、1ラウンド目の
    本文+「続きの生成に失敗」注記付きで完了する(トリアージ指摘: try/except なし)。
    """
    from types import SimpleNamespace

    from core.exceptions import AppError, ErrorCode

    class FailsOnSecondCall(SequenceGateway):
        async def chat_stream(self, *, model, messages, options=None, meta=None):
            if self.calls >= 1:
                self.calls += 1
                raise AppError(ErrorCode.OLLAMA_UNREACHABLE, "boom")
                yield  # pragma: no cover — async generator 化のため
            async for t in super().chat_stream(
                model=model, messages=messages, options=options, meta=meta
            ):
                yield t

    gw = FailsOnSecondCall([(["前半"], "length")])
    result = await ask_tool(
        notebook_id="nb1",
        question="?",
        model=None,
        style="concise",
        retrieval=FakeRetrieval(),
        ollama=gw,
        client=FakeClient(),
        config=SimpleNamespace(
            generation=SimpleNamespace(
                context_budget_ratio=0.8, response_budget_tokens=512, auto_continue_max=2
            ),
            retrieval=SimpleNamespace(top_k=8, min_history_turns=0),
            ollama=SimpleNamespace(default_model="qwen2.5:14b"),
        ),
        notebook_default_model=None,
    )
    assert result["answer"].startswith("前半")
    assert "続きの生成に失敗" in result["answer"]

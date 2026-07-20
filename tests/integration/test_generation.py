import pytest

from core.generation.stream import GenerationDeps, GenerationEvent, GenerationService
from core.retrieval.search import RetrievedChunk


class FakeRetrieval:
    async def search(self, *, notebook_id, query, limit, source_ids=None):
        return [
            RetrievedChunk(
                chunk_id="c1",
                source_id="s1",
                source_title="ARM",
                source_kind="pdf",
                page=42,
                heading_path="§3",
                ord=0,
                text="Cortex content [...]",
                token_count=10,
                score=0.9,
            ),
        ]


class FakeGateway:
    async def chat_stream(self, *, model, messages, options=None, meta=None):
        for tok in ["回", "答", "[^1]"]:
            yield tok
        if meta is not None:
            meta["done_reason"] = "stop"


@pytest.mark.asyncio
async def test_generation_emits_retrieval_then_tokens_then_done():
    svc = GenerationService(
        deps=GenerationDeps(
            retrieval=FakeRetrieval(),
            ollama=FakeGateway(),
        )
    )
    events: list[GenerationEvent] = []
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
    ):
        events.append(ev)
    kinds = [e.kind for e in events]
    assert kinds[0] == "retrieval"
    assert "token" in kinds
    assert kinds[-1] == "done"
    final = next(e for e in events if e.kind == "done")
    assert "回答" in final.data["answer"]
    assert final.data["citations"]
    assert final.data["model_used"] == "qwen2.5:14b"


class RecordingRetrieval:
    def __init__(self):
        self.received_source_ids = "UNSET"

    async def search(self, *, notebook_id, query, limit, source_ids=None):
        self.received_source_ids = source_ids
        return [
            RetrievedChunk(
                chunk_id="c1",
                source_id="s1",
                source_title="ARM",
                source_kind="pdf",
                page=42,
                heading_path="§3",
                ord=0,
                text="Cortex content [...]",
                token_count=10,
                score=0.9,
            ),
        ]


@pytest.mark.asyncio
async def test_generation_forwards_source_ids_to_retrieval():
    retrieval = RecordingRetrieval()
    svc = GenerationService(deps=GenerationDeps(retrieval=retrieval, ollama=FakeGateway()))
    async for _ in svc.run(
        notebook_id="nb",
        model="qwen2.5:14b",
        question="質問",
        history=[],
        num_ctx=8192,
        context_budget_ratio=0.8,
        response_budget_tokens=1024,
        retrieval_top_k=8,
        min_history_turns=1,
        source_ids=["SRC_X"],
    ):
        pass
    assert retrieval.received_source_ids == ["SRC_X"]


class TruncatingGateway:
    """num_predict 上限で打ち切られた Ollama 応答(done_reason=length)を模す。"""

    async def chat_stream(self, *, model, messages, options=None, meta=None):
        for tok in ["回答の", "途中"]:
            yield tok
        if meta is not None:
            meta["done_reason"] = "length"


def _run_args(**overrides):
    base = dict(
        notebook_id="nb",
        model="qwen3:1.7b",
        question="質問",
        history=[],
        num_ctx=8192,
        context_budget_ratio=0.8,
        response_budget_tokens=1024,
        retrieval_top_k=8,
        min_history_turns=1,
    )
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_generation_marks_truncated_answer_with_visible_note():
    """done_reason=length の打ち切りを無言にしない(2026-07-05 実機FB:
    要約プロンプトの回答が文の途中で止まり、原因が見えなかった)。"""
    svc = GenerationService(
        deps=GenerationDeps(retrieval=FakeRetrieval(), ollama=TruncatingGateway())
    )
    events: list[GenerationEvent] = []
    async for ev in svc.run(**_run_args()):
        events.append(ev)

    final = next(e for e in events if e.kind == "done")
    assert final.data["truncated"] is True
    assert "上限" in final.data["answer"]
    # 注記は token イベントとしても流れる(FE 変更なしで画面と履歴に残る)
    token_texts = [e.data.get("text", "") for e in events if e.kind == "token"]
    assert any("上限" in t for t in token_texts)


@pytest.mark.asyncio
async def test_generation_no_note_when_completed_normally():
    svc = GenerationService(
        deps=GenerationDeps(retrieval=FakeRetrieval(), ollama=FakeGateway())
    )
    events: list[GenerationEvent] = []
    async for ev in svc.run(**_run_args()):
        events.append(ev)

    final = next(e for e in events if e.kind == "done")
    assert final.data["truncated"] is False
    assert "上限" not in final.data["answer"]


class ThinkingGateway:
    async def chat_stream(self, *, model, messages, options=None, meta=None):
        from core.ollama.client import ThinkingChunk

        yield ThinkingChunk("思考中の独り言")
        yield "回答"
        if meta is not None:
            meta["done_reason"] = "stop"


@pytest.mark.asyncio
async def test_generation_emits_thinking_events_but_excludes_from_answer():
    """thinking はイベントとして流れ、本文・保存内容には含めない(2026-07-05)。"""
    svc = GenerationService(
        deps=GenerationDeps(retrieval=FakeRetrieval(), ollama=ThinkingGateway())
    )
    events: list[GenerationEvent] = []
    async for ev in svc.run(**_run_args()):
        events.append(ev)

    kinds = [e.kind for e in events]
    assert "thinking" in kinds
    assert kinds.index("thinking") < kinds.index("token")
    final = next(e for e in events if e.kind == "done")
    assert final.data["answer"] == "回答"
    assert "思考中の独り言" not in final.data["answer"]


class SequenceGateway:
    """round ごとに (tokens, done_reason) を返す fake。prefill 検証用に
    受け取った messages を記録する。"""

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
async def test_auto_continue_resumes_with_assistant_prefill():
    gw = SequenceGateway([ (["前半"], "length"), (["後半"], "stop") ])
    svc = GenerationService(deps=GenerationDeps(retrieval=FakeRetrieval(), ollama=gw))
    events = [e async for e in svc.run(**_run_args(auto_continue_max=2))]

    final = next(e for e in events if e.kind == "done")
    assert final.data["answer"] == "前半後半"
    assert final.data["truncated"] is False
    assert final.data["continued_rounds"] == 1
    # 2回目のリクエスト末尾は途中応答の assistant prefill
    assert gw.received_messages[1][-1] == {"role": "assistant", "content": "前半"}
    # continuing イベントが token の間に入る
    cont = next(e for e in events if e.kind == "continuing")
    assert cont.data == {"round": 1, "max": 2}


@pytest.mark.asyncio
async def test_auto_continue_exhausted_appends_note_with_round_count():
    gw = SequenceGateway([ (["a"], "length"), (["b"], "length"), (["c"], "length") ])
    svc = GenerationService(deps=GenerationDeps(retrieval=FakeRetrieval(), ollama=gw))
    events = [e async for e in svc.run(**_run_args(auto_continue_max=2))]
    final = next(e for e in events if e.kind == "done")
    assert final.data["truncated"] is True
    assert final.data["continued_rounds"] == 2
    assert "1024×3回" in final.data["answer"]
    assert final.data["answer"].startswith("abc")


@pytest.mark.asyncio
async def test_auto_continue_zero_keeps_current_behavior():
    gw = SequenceGateway([ (["a"], "length") ])
    svc = GenerationService(deps=GenerationDeps(retrieval=FakeRetrieval(), ollama=gw))
    events = [e async for e in svc.run(**_run_args(auto_continue_max=0))]
    final = next(e for e in events if e.kind == "done")
    assert final.data["truncated"] is True
    assert gw.calls == 1
    assert "1024×1回" in final.data["answer"]
    assert not [e for e in events if e.kind == "continuing"]


@pytest.mark.asyncio
async def test_continuation_error_degrades_gracefully():
    """2ラウンド目のOllamaエラーは途中本文を失わず truncated 扱いで完了する。"""
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

    gw = FailsOnSecondCall([ (["前半"], "length") ])
    svc = GenerationService(deps=GenerationDeps(retrieval=FakeRetrieval(), ollama=gw))
    events = [e async for e in svc.run(**_run_args(auto_continue_max=2))]
    final = next(e for e in events if e.kind == "done")
    assert final.data["truncated"] is True
    assert final.data["answer"].startswith("前半")


@pytest.mark.asyncio
async def test_prefill_answer_included_in_answer_but_not_tokens():
    gw = SequenceGateway([ (["続き"], "stop") ])
    svc = GenerationService(deps=GenerationDeps(retrieval=FakeRetrieval(), ollama=gw))
    events = [e async for e in svc.run(**_run_args(auto_continue_max=0, prefill_answer="既存分"))]
    final = next(e for e in events if e.kind == "done")
    assert final.data["answer"] == "既存分続き"
    token_texts = [e.data["text"] for e in events if e.kind == "token"]
    assert "既存分" not in "".join(token_texts)
    assert gw.received_messages[0][-1] == {"role": "assistant", "content": "既存分"}


def test_strip_truncation_note():
    from core.generation.stream import strip_truncation_note
    body = "回答本文"
    note = "\n\n---\n⚠️ 応答が出力トークン上限(1024×3回)に達したため打ち切られました。"
    assert strip_truncation_note(body + note) == body
    assert strip_truncation_note(body) == body
